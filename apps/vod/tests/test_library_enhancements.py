from datetime import timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.vod import library
from apps.vod.library_jobs import (
    dispatch_pending_enrichment,
    mark_library_refresh,
    request_automatic_enrichment,
)
from apps.vod.models import M3UMovieRelation, VODMetadataState
from core.models import CoreSettings

from . import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryEnhancementTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint

    def test_inactive_accounts_can_preview_category_drafts_without_provider_access(
        self,
    ):
        self.account.is_active = False
        self.account.save()
        with patch("apps.vod.tasks.refresh_library_provider_details.delay") as publish:
            response = self.client.post(
                self.endpoint("cleanup-preview"),
                {
                    "scope": "category",
                    "account": self.account.pk,
                    "category": self.category.pk,
                    "title_cleanup": {},
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        publish.assert_not_called()

    def test_provider_metadata_is_visible_in_editor_without_creating_overrides(self):
        self.movie.custom_properties = {
            "director": "Provider director",
            "age": "12",
            "backdrop_path": ["https://example.com/backdrop.jpg"],
        }
        self.movie.save()
        result = library.canonical_document(self.movie)
        self.assertEqual(result["metadata"]["director"], "Provider director")
        self.assertEqual(result["metadata"]["age_rating"], "12")
        self.assertEqual(
            result["metadata"]["backdrop_url"], "https://example.com/backdrop.jpg"
        )
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.tmdb_metadata, {})

    def test_category_preview_uses_draft_regex_and_raw_source_titles_without_writes(
        self,
    ):
        self.source.custom_properties = {
            "basic_data": {"name": "NF - Film (2020) [4K]"}
        }
        self.source.save()
        library.save_library_settings({"title_rules": ["NF - "]})
        before = list(CoreSettings.objects.values())
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {
                "scope": "category",
                "account": self.account.pk,
                "category": self.category.pk,
                "title_cleanup": {"pattern": r"\[4K\]"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["results"][0]["before"], "NF - Film (2020) [4K]"
        )
        self.assertEqual(response.json()["results"][0]["after"], "Film")
        self.assertEqual(list(CoreSettings.objects.values()), before)
        self.movie.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.movie.clean_title, "")
        self.assertNotIn("title_cleanup", self.source.custom_properties)

    def test_category_preview_validates_even_with_no_imported_sources(self):
        self.source.delete()
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {
                "scope": "category",
                "account": self.account.pk,
                "category": self.category.pk,
                "title_cleanup": {"pattern": "("},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {
                "scope": "category",
                "account": self.account.pk,
                "category": self.category.pk,
                "title_cleanup": {},
            },
            format="json",
        )
        self.assertEqual(response.json()["count"], 0)
        from apps.vod.utils import validate_category_custom_properties

        with self.assertRaises(ValueError):
            validate_category_custom_properties({"title_cleanup": {"pattern": "("}})

    def test_category_preview_paginates_provider_sources_not_merged_titles(self):
        M3UMovieRelation.objects.create(
            movie=self.movie,
            m3u_account=self.account,
            category=self.category,
            stream_id="second",
        )
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {
                "scope": "category",
                "account": self.account.pk,
                "category": self.category.pk,
                "page_size": 1,
                "page": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(len(response.json()["results"]), 1)

    def test_rich_metadata_edits_preserve_identity_and_unedited_translations(self):
        self.movie.tmdb_metadata = {
            "localized": {"fr-FR": {"title": "Original français"}},
            "external_ids": {"imdb_id": "tt999"},
        }
        self.movie.save()
        patch_data = {
            "content_type": "movie",
            "id": self.movie.pk,
            "clean_title": "Film",
            "metadata": {
                "localized": {
                    "de-DE": {"title": "Ein Film", "overview": "Deutsch"},
                    "en-US": {"title": "A film", "overview": "English"},
                },
                "release_date": "2020-05-06",
                "runtime_minutes": 93,
                "age_rating": "FSK 12",
                "director": "Director",
                "actors": "Actor",
                "crew": "Crew",
                "country": "Germany, Spain",
                "keywords": ["Example", "Example"],
                "poster_url": "https://example.com/poster.jpg",
                "backdrop_url": "https://example.com/backdrop.jpg",
                "youtube_trailer": "https://youtu.be/abcdefghijk",
                "external_ids": {
                    "imdb_id": "tt123",
                    "tvdb_id": "123",
                    "wikidata_id": "Q123",
                },
                "is_anime": True,
                "adult": True,
            },
        }
        before_id = self.movie.uuid
        response = self.client.patch(
            self.endpoint("content"), patch_data, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        result = response.json()["metadata"]
        self.assertEqual(result["duration_secs"], 5580)
        self.assertEqual(result["imdb_id"], "tt123")
        self.assertEqual(
            result["metadata"]["localized"]["fr-FR"]["title"], "Original français"
        )
        self.assertEqual(result["metadata"]["youtube_trailer"], "abcdefghijk")
        self.assertEqual(result["metadata"]["keywords"], [{"name": "Example"}])
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.uuid, before_id)
        self.assertEqual(self.movie.name, "NF - Film (2020)")
        self.assertTrue(self.movie.tmdb_lookup_excluded)
        self.assertTrue(self.movie.is_adult)
        from apps.vod.tmdb import apply_manual_overrides

        updated = apply_manual_overrides(
            {"localized": {"de-DE": {"title": "Upstream"}}, "director": "Upstream"},
            self.movie.tmdb_metadata["_manual_overrides"],
        )
        self.assertEqual(updated["localized"]["de-DE"]["title"], "Ein Film")
        self.assertEqual(updated["director"], "Director")

    def test_rich_metadata_rejects_unknown_or_invalid_fields_atomically(self):
        for value in (
            {"localized": {"bad-language": {"title": "Bad"}}},
            {"external_ids": {"imdb_id": "wrong"}},
            {"runtime_minutes": -1},
            {"poster_url": "javascript:alert(1)"},
            {"youtube_trailer": "https://evil.example/video"},
            {"unknown": "value"},
        ):
            with self.subTest(value=value):
                response = self.client.patch(
                    self.endpoint("content"),
                    {
                        "content_type": "movie",
                        "id": self.movie.pk,
                        "display_name": "Must not save",
                        "metadata": value,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.movie.refresh_from_db()
                self.assertEqual(self.movie.display_name, "")


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryOutboxTests(TestCase):
    def setUp(self):
        cache.clear()
        library.save_library_settings({"api_token": "synthetic", "auto_enrich": True})

    @patch("apps.vod.tasks.dispatch_pending_library_enrichment.apply_async")
    def test_competing_job_keeps_a_durable_deduplicated_followup(self, publish):
        state = VODMetadataState.objects.create(
            status="running",
            task_id="cleanup",
            progress={"operation": "cleanup"},
            selection=[["movie", 1]],
        )
        with self.captureOnCommitCallbacks(execute=True):
            request_automatic_enrichment([("movie", 2), ("movie", 2)])
        self.assertFalse(dispatch_pending_enrichment())
        state.refresh_from_db()
        self.assertEqual(state.pending_enrichment, [["movie", 2]])
        self.assertEqual(state.task_id, "cleanup")
        self.assertTrue(publish.called)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    @patch("core.utils.is_task_lock_held")
    def test_waits_for_imports_and_recovers_expired_refresh_markers(
        self, held, publish
    ):
        request_automatic_enrichment([("movie", 2)])
        mark_library_refresh(123, running=True)
        held.return_value = True
        self.assertFalse(dispatch_pending_enrichment())
        held.return_value = False
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(dispatch_pending_enrichment())
        state = VODMetadataState.objects.get(pk=1)
        self.assertEqual(state.status, "queued")
        self.assertEqual(state.selection, [["movie", 2]])
        self.assertEqual(state.pending_enrichment, [])
        self.assertEqual(state.refreshing_accounts, [])
        self.assertEqual(publish.call_count, 1)

    def test_stale_worker_is_resumable_and_manual_cancellation_is_respected(self):
        state = VODMetadataState.objects.create(
            status="running",
            task_id="old",
            selection=[["movie", 1]],
            pending_enrichment=[["movie", 2]],
            job_heartbeat=timezone.now() - timedelta(hours=7),
        )
        self.assertTrue(dispatch_pending_enrichment())
        state.refresh_from_db()
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.selection, [["movie", 1]])
        self.assertEqual(state.pending_enrichment, [["movie", 2]])
        state.status = "cancelled"
        state.save()
        self.assertTrue(dispatch_pending_enrichment())
        state.refresh_from_db()
        self.assertEqual(state.status, "cancelled")
