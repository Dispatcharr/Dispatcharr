"""Selection pagination and explicit manual Library operations stay source-safe."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.vod import library
from apps.vod.models import Movie, VODMetadataState
from apps.vod.tmdb import TMDBError

from . import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryRefinementTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint
    selection = fixtures.LibraryTests.selection
    metadata = fixtures.LibraryTests.metadata

    def test_selection_preview_paginates_every_selected_title_without_writes(self):
        movies = Movie.objects.bulk_create(
            [
                Movie(name=f"Selected {index}", tmdb_lookup_excluded=index % 2 == 0)
                for index in range(61)
            ]
        )
        refs = [{"content_type": "movie", "id": row.pk} for row in movies]
        before = list(Movie.objects.values())
        seen = []
        for page in range(1, 4):
            response = self.client.post(
                self.endpoint("cleanup-preview"),
                {"items": refs, "page": page, "page_size": 25},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.data)
            data = response.json()
            self.assertEqual(
                (data["count"], data["page"], data["page_size"]), (61, page, 25)
            )
            self.assertLessEqual(len(data["results"]), 25)
            seen.extend(row["id"] for row in data["results"])
            for row in data["results"]:
                self.assertEqual(
                    row["locked"], movies[seen.index(row["id"])].tmdb_lookup_excluded
                )
        self.assertEqual(seen, [row.pk for row in movies])
        self.assertEqual(before, list(Movie.objects.values()))
        self.assertFalse(VODMetadataState.objects.exists())

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_cleanup_override_is_opt_in_and_keeps_protection(self, _publish):
        library.save_library_settings({"title_rules": ["NF -"]})
        self.movie.tmdb_lookup_excluded = True
        self.movie.save()
        for include, expected in ((False, ""), (True, "Film")):
            response = self.client.post(
                self.endpoint("bulk"),
                self.selection(operation="cleanup", include_protected=include),
                format="json",
            )
            self.assertEqual(response.status_code, 202, response.data)
            state = VODMetadataState.objects.get(pk=1)
            self.assertEqual(state.progress["include_protected"], include)
            with patch("apps.vod.library.tmdb_client") as client:
                library.run_library_job(state.task_id)
                client.assert_not_called()
            self.movie.refresh_from_db()
            self.assertEqual(self.movie.clean_title, expected)
            self.assertTrue(self.movie.tmdb_lookup_excluded)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_manual_enrichment_override_preserves_lock_on_success_and_failure(
        self, _publish
    ):
        library.save_library_settings({"api_token": "test-token"})
        self.movie.tmdb_lookup_excluded = True
        self.movie.tmdb_id = "123"
        self.movie.save()
        for fails in (False, True):
            with patch("apps.vod.library.tmdb_client") as client:
                client.return_value.details.return_value = self.metadata()
                if fails:
                    client.return_value.details.side_effect = TMDBError("Unavailable")
                state = library.queue_library_job(
                    "enrich", [("movie", self.movie.pk)], include_protected=True
                )
                library.run_library_job(state["task_id"])
            self.movie.refresh_from_db()
            self.assertTrue(self.movie.tmdb_lookup_excluded)
            self.assertEqual(self.movie.tmdb_status, "failed" if fails else "matched")

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_resume_retains_only_the_explicit_job_override(self, _publish):
        state = VODMetadataState.objects.create(
            pk=1,
            status="cancelled",
            selection=[["movie", self.movie.pk]],
            progress={
                "operation": "cleanup",
                "processed": 0,
                "include_protected": True,
            },
        )
        response = self.client.post(self.endpoint("resume-job"), {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        state.refresh_from_db()
        self.assertTrue(state.progress["include_protected"])
        with self.assertRaisesMessage(ValueError, "already queued or running"):
            library.queue_library_job("cleanup", [("movie", 999)], automatic=True)
        state.refresh_from_db()
        self.assertEqual(state.selection, [["movie", self.movie.pk]])
        with self.assertRaisesMessage(ValueError, "Automatic jobs cannot override"):
            library.queue_library_job(
                "cleanup", [], automatic=True, include_protected=True
            )

    def test_override_is_rejected_for_protection_and_reset_actions(self):
        for operation in ("lock", "unlock", "reset"):
            response = self.client.post(
                self.endpoint("bulk"),
                self.selection(operation=operation, include_protected=True),
                format="json",
            )
            self.assertEqual(response.status_code, 400)

    def test_simple_metadata_and_date_filters_distinguish_ids_from_enrichment(self):
        self.movie.imdb_id = "tt123"
        self.movie.tmdb_metadata = {"genres": [{"name": "Science Fiction"}]}
        self.movie.library_added_at = timezone.now() - timedelta(days=20)
        self.movie.save()
        for params, count in (
            ({"metadata_status": "missing_id"}, 1),
            ({"metadata_status": "missing_external_ids"}, 0),
            ({"metadata_status": "missing_metadata"}, 1),
            ({"genre": "fiction"}, 1),
            ({"genre": "Drama"}, 0),
            ({"added_since": timezone.localdate().isoformat()}, 0),
            (
                {
                    "added_since": (
                        timezone.localdate() - timedelta(days=21)
                    ).isoformat()
                },
                1,
            ),
        ):
            response = self.client.get(self.endpoint(), params)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.json()["count"], count, params)
        self.assertEqual(
            self.client.get(self.endpoint(), {"added_since": "invalid"}).status_code,
            400,
        )

    def test_missing_external_ids_respects_manual_imdb_tvdb_and_wikidata_ids(self):
        for field, value in (
            ("imdb_id", "tt123"),
            ("tvdb_id", "123"),
            ("wikidata_id", "Q42"),
        ):
            self.movie.tmdb_metadata = {"external_ids": {field: value}}
            self.movie.save()
            response = self.client.get(
                self.endpoint(), {"metadata_status": "missing_external_ids"}
            )
            self.assertEqual(response.json()["count"], 0, field)
