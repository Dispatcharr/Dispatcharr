"""Filtered Library selections are independent of the displayed page."""

from unittest.mock import patch

from django.test import TestCase

from apps.vod import library
from apps.vod.models import M3UMovieRelation, Movie, VODMetadataState

from . import test_library as fixtures


class LibrarySelectionTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint

    def filtered(self, view="titles", **extra):
        return {
            "all_matching": True,
            "filters": {"view": view, "account": self.account.pk},
            **extra,
        }

    def test_all_matching_titles_are_distinct_and_respect_exclusions(self):
        duplicate = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, stream_id="second"
        )
        other = Movie.objects.create(name="Other title", tmdb_lookup_excluded=True)
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=other, stream_id="other"
        )
        self.assertEqual(len(library.selected_content(self.filtered())), 2)
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            self.filtered(page_size=1),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(response.data["protected_count"], 1)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["item"]["content_id"], self.movie.pk
        )
        response = self.client.post(
            self.endpoint("bulk"),
            self.filtered(
                operation="lock",
                excluded=[{"content_type": "movie", "id": other.pk}],
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.movie.refresh_from_db()
        self.assertTrue(self.movie.tmdb_lookup_excluded)
        duplicate.refresh_from_db()
        self.assertEqual(duplicate.manual_metadata, {})

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_filtered_job_snapshots_all_pages_but_not_excluded_titles(self, _publish):
        movies = Movie.objects.bulk_create(
            [Movie(name=f"Page {index}") for index in range(30)]
        )
        M3UMovieRelation.objects.bulk_create(
            [
                M3UMovieRelation(
                    m3u_account=self.account, movie=movie, stream_id=str(index)
                )
                for index, movie in enumerate(movies, start=100)
            ]
        )
        response = self.client.post(
            self.endpoint("bulk"),
            self.filtered(
                operation="cleanup",
                excluded=[{"content_type": "movie", "id": self.movie.pk}],
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 202, response.data)
        state = VODMetadataState.objects.get(pk=1)
        self.assertEqual(len(state.selection), 30)
        self.assertEqual(
            {pk for kind, pk in state.selection}, {movie.pk for movie in movies}
        )

    def test_filtered_source_edits_preserve_other_sources_and_metadata(self):
        other = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            stream_id="second",
            manual_metadata={"audio_languages": ["eng"], "resolution": "720p"},
        )
        self.source.manual_metadata = {"audio_languages": ["ger"]}
        self.source.save()
        response = self.client.patch(
            self.endpoint("source-metadata"),
            self.filtered(
                "sources",
                excluded=[{"content_type": "movie", "id": self.source.pk}],
                manual_metadata={"resolution": "1080p", "audio_languages": None},
            ),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        other.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(other.manual_metadata, {"resolution": "1080p"})
        self.assertEqual(self.source.manual_metadata, {"audio_languages": ["ger"]})

    def test_empty_filtered_selection_is_not_the_entire_catalog(self):
        response = self.client.patch(
            self.endpoint("source-metadata"),
            {
                **self.filtered("sources", manual_metadata={"resolution": "1080p"}),
                "filters": {"view": "sources", "search": "Not in the catalog"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)
        self.source.refresh_from_db()
        self.assertEqual(self.source.manual_metadata, {})

    def test_filtered_source_updates_cover_more_than_one_batch(self):
        M3UMovieRelation.objects.bulk_create(
            [
                M3UMovieRelation(
                    m3u_account=self.account,
                    movie=self.movie,
                    stream_id=f"batch-{index}",
                    manual_metadata={"audio_languages": ["eng"]},
                )
                for index in range(1001)
            ]
        )
        response = self.client.patch(
            self.endpoint("source-metadata"),
            self.filtered("sources", manual_metadata={"resolution": "1080p"}),
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1002)
        sources = M3UMovieRelation.objects.filter(m3u_account=self.account)
        self.assertEqual(
            sources.filter(manual_metadata__resolution="1080p").count(), 1002
        )
        self.assertEqual(
            sources.filter(manual_metadata__audio_languages=["eng"]).count(), 1001
        )

    def test_filtered_selection_cannot_move_sources_or_mix_selection_modes(self):
        for body in (
            self.filtered("sources", target_id=self.movie.pk),
            self.filtered("titles", manual_metadata={"resolution": "1080p"}),
            self.filtered(
                "sources",
                items=[{"content_type": "movie", "id": self.source.pk}],
                manual_metadata={"resolution": "1080p"},
            ),
            {
                "items": [{"content_type": "movie", "id": self.source.pk}],
                "excluded": [{"content_type": "movie", "id": self.source.pk}],
                "manual_metadata": {"resolution": "1080p"},
            },
        ):
            with self.subTest(body=body):
                response = self.client.patch(
                    self.endpoint("source-metadata"), body, format="json"
                )
                self.assertEqual(response.status_code, 400, response.data)
        self.source.refresh_from_db()
        self.assertEqual(self.source.manual_metadata, {})

    def test_standard_users_cannot_apply_filtered_selections(self):
        self.client.force_authenticate(self.user)
        response = self.client.patch(
            self.endpoint("source-metadata"),
            self.filtered("sources", manual_metadata={"resolution": "1080p"}),
            format="json",
        )
        self.assertEqual(response.status_code, 403)
