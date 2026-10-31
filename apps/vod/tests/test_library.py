from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.vod import library
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Series,
    VODCategory,
    VODMetadataState,
)
from apps.vod.selection import resolve_content
from core.models import CoreSettings


class LibrarySchemaTests(SimpleTestCase):
    def test_library_openapi_schema_validates_in_isolation(self):
        from django.urls import include, path
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema
        from rest_framework.routers import SimpleRouter

        from apps.vod.library_api import VODLibraryViewSet

        router = SimpleRouter()
        router.register("library", VODLibraryViewSet, basename="library")
        schema = SchemaGenerator(
            patterns=[path("api/vod/", include(router.urls))]
        ).get_schema(public=True)
        validate_schema(schema)
        self.assertIn("/api/vod/library/", schema["paths"])
        self.assertIn("/api/vod/library/source-metadata/", schema["paths"])
        self.assertIn("/api/vod/library/tmdb-match/", schema["paths"])
        self.assertIn("/api/vod/library/details/", schema["paths"])
        self.assertIn("/api/vod/library/canonical-targets/", schema["paths"])


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.admin = User.objects.create_user(
            username="library-admin", password="test", user_level=10
        )
        self.user = User.objects.create_user(
            username="library-user", password="test", user_level=1
        )
        self.client.force_authenticate(self.admin)
        self.account = M3UAccount.objects.create(
            name="Provider", account_type="XC", is_active=True
        )
        self.category = VODCategory.objects.create(
            name="English", category_type="movie"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            metadata_defaults={"audio_languages": ["eng"]},
        )
        self.movie = Movie.objects.create(name="NF - Film (2020)", year=2020)
        self.source = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            category=self.category,
            stream_id="10",
            custom_properties={"basic_data": {"name": "NF - Film (2020)"}},
        )

    def endpoint(self, action="list"):
        return reverse(f"api:vod:library-{action}")

    def selection(self, **extra):
        return {"items": [{"content_type": "movie", "id": self.movie.pk}], **extra}

    def metadata(self, **extra):
        return {
            "id": "123",
            "imdb_id": "tt123",
            "localized": {"en-US": {"title": "Film", "overview": "Description"}},
            "poster_url": "https://image.tmdb.org/t/p/w500/test.jpg",
            **extra,
        }

    def test_canonical_and_source_views_keep_source_metadata_separate(self):
        other = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            category=self.category,
            stream_id="11",
            manual_metadata={"audio_languages": ["ger"], "resolution": "1080p"},
        )
        result = self.client.get(self.endpoint()).json()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["results"][0]["source_count"], 2)
        self.assertEqual(
            result["results"][0]["metadata_summary"]["audio_languages"], ["eng", "ger"]
        )
        sources = self.client.get(
            self.endpoint(), {"view": "sources", "page_size": 1}
        ).json()
        self.assertEqual(sources["count"], 2)
        self.assertEqual(sources["results"][0]["source_count"], 2)
        self.assertEqual(
            sources["results"][0]["metadata_summary"]["audio_languages"], ["eng"]
        )
        second = self.client.get(
            self.endpoint(), {"view": "sources", "page_size": 1, "page": 2}
        ).json()["results"][0]
        self.assertEqual(second["source_id"], other.pk)
        self.assertEqual(
            second["effective_metadata"]["values"]["audio_languages"], ["ger"]
        )

    def test_inactive_sources_do_not_appear(self):
        self.account.is_active = False
        self.account.save()
        self.assertEqual(self.client.get(self.endpoint()).json()["count"], 0)

    def test_format_summary_is_unique_and_scoped_to_visible_sources(self):
        self.source.container_extension = "MKV"
        self.source.save(update_fields=["container_extension"])
        for stream_id, extension in (("11", "mp4"), ("12", "mkv"), ("13", None)):
            M3UMovieRelation.objects.create(
                m3u_account=self.account,
                movie=self.movie,
                category=self.category,
                stream_id=stream_id,
                container_extension=extension,
            )
        title = self.client.get(self.endpoint()).json()["results"][0]
        self.assertEqual(
            title["metadata_summary"]["container_extensions"], ["mkv", "mp4"]
        )
        sources = self.client.get(self.endpoint(), {"view": "sources"}).json()[
            "results"
        ]
        formats = {
            row["provider_id"]: row["metadata_summary"]["container_extensions"]
            for row in sources
        }
        self.assertEqual(
            formats, {"10": ["mkv"], "11": ["mp4"], "12": ["mkv"], "13": []}
        )
        filtered = self.client.get(
            self.endpoint(), {"container_extension": "mp4"}
        ).json()["results"][0]
        self.assertEqual(filtered["source_count"], 1)
        self.assertEqual(filtered["metadata_summary"]["container_extensions"], ["mp4"])

    def test_series_format_summary_does_not_infer_a_movie_or_episode_format(self):
        series = Series.objects.create(name="Series")
        M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=series,
            external_series_id="20",
        )
        for view in ("titles", "sources"):
            result = self.client.get(
                self.endpoint(), {"type": "series", "view": view}
            ).json()
            self.assertEqual(result["count"], 1)
            self.assertEqual(
                result["results"][0]["metadata_summary"]["container_extensions"], []
            )

    def test_normal_users_cannot_read_sources_settings_or_mutate(self):
        self.client.force_authenticate(self.user)
        for path, method, payload in (
            (self.endpoint(), "get", {"view": "sources"}),
            (self.endpoint("settings"), "get", {}),
            (self.endpoint("bulk"), "post", self.selection(operation="unlock")),
        ):
            response = getattr(self.client, method)(path, payload, format="json")
            self.assertEqual(response.status_code, 403)

    @patch("apps.vod.library_connection.Client.validate")
    def test_settings_never_return_the_api_token(self, _validate):
        response = self.client.put(
            self.endpoint("settings"),
            {"api_token": "private-token", "languages": ["de-de", "en-US"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["languages"], ["de-DE", "en-US"])
        self.assertTrue(response.json()["token_configured"])
        self.assertNotIn("private-token", str(response.json()))
        generic = self.client.get(reverse("api:core:coresettings-list")).json()
        self.assertNotIn("private-token", str(generic))
        self.assertNotIn("vod_library", str(generic))
        self.assertEqual(
            self.client.post(
                reverse("api:core:coresettings-list"),
                {"key": "vod_library", "name": "Bypass", "value": {}},
                format="json",
            ).status_code,
            400,
        )

    def test_settings_validate_language_regions_and_rule_limits(self):
        for data in (
            {"languages": ["ger"]},
            {"languages": []},
            {"languages": ["en-US"] * 11},
            {"year_rules": [{"value": "Year"}]},
            {"title_rules": ["x"] * 21},
            {"unknown": True},
        ):
            self.assertEqual(
                self.client.put(
                    self.endpoint("settings"), data, format="json"
                ).status_code,
                400,
            )

    def test_settings_keep_display_order_and_save_sections_independently(
        self,
    ):
        library.save_library_settings({"title_rules": ["NF - "]})
        response = self.client.put(
            self.endpoint("settings"),
            {"languages": ["es-ES", "en-US", "de-de", "DE-DE"], "auto_enrich": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["languages"], ["es-ES", "en-US", "de-DE"])
        self.assertEqual(
            response.json()["title_rules"], [{"value": "NF - ", "enabled": True}]
        )
        response = self.client.put(
            self.endpoint("settings"), {"title_rules": ["4K - "]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["languages"], ["es-ES", "en-US", "de-DE"])
        self.assertTrue(response.json()["auto_enrich"])

    def test_new_selections_allow_five_languages_without_truncating_old_settings(self):
        languages = ["es-ES", "en-US", "de-DE", "fr-FR", "it-IT", "ja-JP"]
        response = self.client.put(
            self.endpoint("settings"), {"languages": languages}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.put(
            self.endpoint("settings"), {"languages": languages[:5]}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["languages"], languages[:5])
        CoreSettings.objects.update_or_create(
            key=library.SETTINGS_KEY,
            defaults={"name": "VOD library", "value": {"languages": languages}},
        )
        response = self.client.get(self.endpoint("settings"))
        self.assertEqual(response.json()["languages"], languages)
        response = self.client.put(
            self.endpoint("settings"), {"prefer_artwork": False}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["languages"], languages)

    def test_refresh_retains_unrequested_translations_only_for_the_same_tmdb_title(
        self,
    ):
        first = self.metadata(
            localized={"ja-JP": {"title": "保存", "overview": "Saved Japanese"}}
        )
        content = library.apply_tmdb(self.movie, first)
        content = library.apply_tmdb(content, self.metadata())
        self.assertEqual(
            content.tmdb_metadata["localized"]["ja-JP"]["overview"], "Saved Japanese"
        )
        content = library.move_source_to_tmdb(
            "movie", self.source.pk, self.metadata(id="456", imdb_id="tt456")
        )
        self.assertNotIn("ja-JP", content.tmdb_metadata["localized"])

    def test_settings_reject_duplicate_cleanup_rules_without_partial_updates(self):
        library.save_library_settings({"title_rules": ["NF - "]})
        before = library.library_settings()
        for data in (
            {"title_rules": ["NF - ", "NF - "]},
            {
                "year_rules": [
                    {"value": "(YYYY)", "position": "end"},
                    {"value": "(YYYY)", "position": "anywhere", "enabled": False},
                ]
            },
            {"year_rules": [" {year} ", "YYYY"]},
            {"year_rules": [{"value": "YYYY YYYY"}]},
            {"year_rules": [{"value": "Year"}]},
            {"title_rules": [" "]},
        ):
            with self.subTest(data=data):
                response = self.client.put(
                    self.endpoint("settings"),
                    {**data, "auto_enrich": True},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(library.library_settings(), before)

    def test_cleanup_field_saves_keep_other_rules_and_metadata_settings(self):
        library.save_library_settings(
            {
                "languages": ["de-DE", "en-US"],
                "title_rules": ["DE - ", "de - ", "DE -"],
                "year_rules": [
                    {"value": "(YYYY)", "position": "anywhere", "enabled": False}
                ],
            }
        )
        response = self.client.put(
            self.endpoint("settings"),
            {"title_rules": ["de - ", "DE - "]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["languages"], ["de-DE", "en-US"])
        self.assertEqual(
            response.json()["year_rules"],
            [{"value": "(YYYY)", "position": "anywhere", "enabled": False}],
        )
        response = self.client.put(
            self.endpoint("settings"),
            {"year_rules": [{"value": "[YYYY]", "position": "end", "enabled": True}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["title_rules"],
            [{"value": "de - ", "enabled": True}, {"value": "DE - ", "enabled": True}],
        )

    def test_empty_selection_does_not_mean_the_full_library(self):
        self.assertEqual(
            self.client.post(
                self.endpoint("bulk"), {"operation": "reset"}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                self.endpoint("cleanup-preview"), {}, format="json"
            ).status_code,
            400,
        )

    def test_preview_is_read_only_and_uses_configured_prefixes(self):
        library.save_library_settings({"title_rules": ["NF -"]})
        response = self.client.post(
            self.endpoint("cleanup-preview"), self.selection(), format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["after"], "Film")
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.clean_title, "")
        self.assertEqual(VODMetadataState.objects.count(), 0)

    def test_cleanup_previews_use_the_source_suffix_not_a_stale_canonical_year(self):
        self.movie.name = "2012 - 2009"
        self.movie.year = 2012
        self.movie.save()
        self.source.custom_properties = {"basic_data": {"name": "2012 - 2009"}}
        self.source.save()
        before = Movie.objects.values().get(pk=self.movie.pk)
        for request in (
            self.selection(),
            {"scope": "catalog", "search": "2012"},
            {
                "scope": "category",
                "account": self.account.pk,
                "category": self.category.pk,
            },
        ):
            with self.subTest(scope=request.get("scope", "selection")):
                response = self.client.post(
                    self.endpoint("cleanup-preview"), request, format="json"
                )
                self.assertEqual(response.status_code, 200, response.data)
                row = response.json()["results"][0]
                self.assertEqual((row["after"], row["year"]), ("2012", 2009))
        self.assertEqual(Movie.objects.values().get(pk=self.movie.pk), before)
        self.assertEqual(VODMetadataState.objects.count(), 0)

    def test_cleanup_does_not_reuse_unproven_canonical_year_for_title_numbers(self):
        for title, stale_year in (("2012", 2012), ("Class of 1984", 1984)):
            with self.subTest(title=title):
                self.movie.name, self.movie.year = title, stale_year
                self.movie.save()
                self.source.custom_properties = {"basic_data": {"name": title}}
                self.source.save()
                self.assertEqual(library.cleanup_for_source(self.source), (title, None))
        self.movie.tmdb_metadata = {"release_date": "1982-01-01"}
        self.movie.save()
        self.assertEqual(
            library.cleanup_for_source(self.source), ("Class of 1984", 1982)
        )

    def test_cleanup_uses_a_source_year_to_remove_a_bare_release_suffix(self):
        self.source.custom_properties = {
            "basic_data": {"name": "Blade Runner 2049 2017", "year": 2017}
        }
        self.source.save()
        self.assertEqual(
            library.cleanup_for_source(self.source), ("Blade Runner 2049", 2017)
        )

    def test_catalog_preview_uses_unsaved_rules_without_writes_or_network(self):
        self.movie.tmdb_lookup_excluded = True
        self.movie.save(update_fields=["tmdb_lookup_excluded"])
        before_settings = list(CoreSettings.objects.values())
        before_movie = Movie.objects.values().get(pk=self.movie.pk)
        before_source = M3UMovieRelation.objects.values().get(pk=self.source.pk)
        with patch(
            "apps.vod.library.Client", side_effect=AssertionError("No TMDB request")
        ):
            response = self.client.post(
                self.endpoint("cleanup-preview"),
                {
                    "scope": "catalog",
                    "search": "Film",
                    "title_rules": ["NF - "],
                    "year_rules": ["(YYYY)"],
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["after"], "Film")
        self.assertEqual(response.json()["results"][0]["year"], 2020)
        self.assertTrue(response.json()["results"][0]["locked"])
        self.assertEqual(list(CoreSettings.objects.values()), before_settings)
        self.assertEqual(Movie.objects.values().get(pk=self.movie.pk), before_movie)
        self.assertEqual(
            M3UMovieRelation.objects.values().get(pk=self.source.pk), before_source
        )
        self.assertEqual(VODMetadataState.objects.count(), 0)

    def test_catalog_preview_missing_ids_paginates_and_excludes_inactive_sources(self):
        for index in range(3):
            movie = Movie.objects.create(
                name=f"Film {index}", tmdb_id="123" if index == 0 else None
            )
            M3UMovieRelation.objects.create(
                movie=movie, m3u_account=self.account, stream_id=f"p{index}"
            )
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {"scope": "catalog", "missing_tmdb_only": True, "page_size": 1, "page": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 3)
        self.assertEqual(len(response.json()["results"]), 1)
        self.assertEqual(response.json()["page"], 2)
        self.account.is_active = False
        self.account.save(update_fields=["is_active"])
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {"scope": "catalog", "missing_tmdb_only": True},
            format="json",
        )
        self.assertEqual(response.json()["count"], 0)

    def test_catalog_preview_rejects_invalid_rules_and_unbounded_queries(self):
        for extra in (
            {},
            {"search": "Film", "page_size": 51},
            {"search": "Film", "year_rules": ["invalid"]},
            {"search": "Film", "title_rules": ["NF", "NF"]},
            {"search": "Film", **self.selection()},
        ):
            with self.subTest(extra=extra):
                response = self.client.post(
                    self.endpoint("cleanup-preview"),
                    {"scope": "catalog", **extra},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.endpoint("cleanup-preview"),
            {"scope": "catalog", "missing_tmdb_only": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_manual_canonical_edits_do_not_change_provider_identity(self):
        response = self.client.patch(
            self.endpoint("content"),
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "display_name": "My title",
                "description": "My description",
                "year": 2021,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metadata"]["name"], "My title")
        self.assertEqual(response.json()["metadata"]["year"], 2021)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.name, "NF - Film (2020)")
        self.assertEqual(self.movie.year, 2020)
        self.assertTrue(self.movie.tmdb_lookup_excluded)
        self.assertEqual(self.source.movie_id, self.movie.pk)

    def test_bulk_source_edits_are_normalized_and_atomic(self):
        url = self.endpoint("source-metadata")
        payload = {
            "items": [{"content_type": "movie", "id": self.source.pk}],
            "manual_metadata": {"audio_languages": ["de", "eng"]},
        }
        self.assertEqual(
            self.client.patch(url, payload, format="json").status_code, 200
        )
        self.source.refresh_from_db()
        self.assertEqual(self.source.manual_metadata["audio_languages"], ["ger", "eng"])
        payload["items"].append({"content_type": "movie", "id": 999999})
        payload["manual_metadata"] = {"resolution": "2160p"}
        self.assertEqual(
            self.client.patch(url, payload, format="json").status_code, 404
        )
        self.source.refresh_from_db()
        self.assertNotIn("resolution", self.source.manual_metadata)

    def test_matching_preserves_public_aliases_and_exact_source_ids(self):
        donor = Movie.objects.create(name="Duplicate", tmdb_id="123")
        donor_uuid, donor_id = donor.uuid, donor.pk
        source = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=donor,
            category=self.category,
            stream_id="99",
        )
        result = library.apply_tmdb(self.movie, self.metadata())
        source.refresh_from_db()
        self.assertEqual(source.movie_id, result.pk)
        resolved, _ = resolve_content("movie", donor_id)
        self.assertEqual(resolved.pk, result.pk)
        resolved, _ = resolve_content("movie", donor_uuid, by_uuid=True)
        self.assertEqual(resolved.pk, result.pk)
        self.source.refresh_from_db()
        self.assertEqual(self.source.stream_id, "10")

    def test_conflicting_external_ids_abort_matching(self):
        self.movie.imdb_id = "tt-other"
        self.movie.save()
        with self.assertRaises(ValueError):
            library.apply_tmdb(self.movie, self.metadata())
        self.movie.refresh_from_db()
        self.assertIsNone(self.movie.tmdb_id)

    def test_source_match_does_not_move_other_provider_sources(self):
        other = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            category=self.category,
            stream_id="12",
        )
        target = library.move_source_to_tmdb("movie", self.source.pk, self.metadata())
        self.source.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.source.movie_id, target.pk)
        self.assertEqual(other.movie_id, self.movie.pk)
        self.assertNotEqual(target.pk, self.movie.pk)

    def test_series_source_match_keeps_other_episode_inventories_separate(self):
        series = Series.objects.create(name="Two inventories")
        sources = [
            M3USeriesRelation.objects.create(
                m3u_account=self.account, series=series, external_series_id=str(value)
            )
            for value in (1, 2)
        ]
        episode = Episode.objects.create(
            series=series, season_number=1, episode_number=1, name="Episode"
        )
        episodes = [
            M3UEpisodeRelation.objects.create(
                m3u_account=self.account,
                episode=episode,
                series_relation=source,
                stream_id=str(100 + index),
            )
            for index, source in enumerate(sources)
        ]
        target = library.move_source_to_tmdb("series", sources[0].pk, self.metadata())
        episodes[0].refresh_from_db()
        episodes[1].refresh_from_db()
        self.assertEqual(episodes[0].episode.series_id, target.pk)
        self.assertEqual(episodes[1].episode.series_id, series.pk)
        self.assertEqual(episodes[0].series_relation_id, sources[0].pk)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_cleanup_job_never_calls_tmdb_or_changes_source_identity(self, publish):
        library.save_library_settings({"title_rules": ["NF -"]})
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.endpoint("bulk"),
                self.selection(operation="cleanup"),
                format="json",
            )
        self.assertEqual(response.status_code, 202)
        publish.assert_called_once()
        state = VODMetadataState.objects.get(pk=1)
        with patch(
            "apps.vod.library.tmdb_client",
            side_effect=AssertionError("Cleanup must not call TMDB"),
        ):
            library.run_library_job(state.task_id)
        self.movie.refresh_from_db()
        state.refresh_from_db()
        self.assertEqual(state.status, "complete")
        self.assertEqual(self.movie.clean_title, "Film")
        self.assertEqual(self.movie.name, "NF - Film (2020)")

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_enrichment_locks_attempts_and_respects_manual_overrides(self, _publish):
        library.save_library_settings(
            {"api_token": "test-token", "match_missing": True}
        )
        state = library.queue_library_job("enrich", [("movie", self.movie.pk)])
        with patch("apps.vod.library.tmdb_client") as factory:
            factory.return_value.search_outcome.return_value = ("123", "matched", 1)
            factory.return_value.details.return_value = self.metadata()
            library.run_library_job(state["task_id"])
        self.movie.refresh_from_db()
        self.assertTrue(self.movie.tmdb_lookup_excluded)
        self.assertEqual(self.movie.tmdb_status, "matched")
        self.assertEqual(self.movie.name, "NF - Film (2020)")

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_cancelled_job_does_not_apply_a_pending_network_result(self, _publish):
        library.save_library_settings({"api_token": "test-token"})
        self.movie.tmdb_id = "123"
        self.movie.save()
        state = library.queue_library_job("enrich", [("movie", self.movie.pk)])

        def cancel(*args, **kwargs):
            VODMetadataState.objects.filter(pk=1).update(status="cancelled")
            return self.metadata()

        with patch("apps.vod.library.tmdb_client") as factory:
            factory.return_value.details.side_effect = cancel
            library.run_library_job(state["task_id"])
        self.movie.refresh_from_db()
        self.assertFalse(self.movie.tmdb_metadata)
        self.assertEqual(VODMetadataState.objects.get(pk=1).status, "cancelled")

    def test_manual_empty_values_are_intentional(self):
        self.movie.description = "Provider description"
        self.movie.genre = "Action"
        self.movie.save()
        response = self.client.patch(
            self.endpoint("content"),
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "description": "",
                "genre": "",
                "year": None,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        document = response.json()["metadata"]
        self.assertEqual(document["description"], "")
        self.assertEqual(document["genre"], "")
        self.assertIsNone(document["year"])

    def test_translations_and_language_order_never_replace_provider_base_fields(self):
        self.movie.clean_title = "Clean provider title"
        self.movie.description = "Provider description"
        self.movie.save()
        metadata = self.metadata(
            localized={
                "de-DE": {"title": "Deutsch", "overview": "Beschreibung"},
                "en-US": {"title": "English", "overview": "Description"},
            }
        )
        content = library.apply_tmdb(self.movie, metadata)
        for languages in (["en-US", "de-DE"], ["de-DE", "en-US"]):
            document = library.canonical_document(content, {"languages": languages})
            self.assertEqual(
                document["name"], metadata["localized"][languages[0]]["title"]
            )
            self.assertEqual(document["description"], "Provider description")
            self.assertEqual(document["metadata"]["localized"], metadata["localized"])
        self.assertEqual(content.display_name, "")
        self.assertEqual(content.clean_title, "Clean provider title")

    def test_base_edits_are_not_written_into_an_arbitrary_translation_and_survive_refresh(
        self,
    ):
        library.save_library_settings({"languages": ["de-DE", "en-US"]})
        self.movie.tmdb_metadata = self.metadata()
        self.movie.save()
        response = self.client.patch(
            self.endpoint("content"),
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "display_name": "Curated",
                "description": "Local description",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.movie.refresh_from_db()
        overrides = self.movie.tmdb_metadata["_manual_overrides"]
        self.assertEqual(
            overrides["library"], {"title": "Curated", "overview": "Local description"}
        )
        self.assertNotIn("localized", overrides)
        library.save_library_settings({"languages": ["es-ES", "en-US"]})
        content = library.apply_tmdb(self.movie, self.metadata())
        document = library.canonical_document(content)
        self.assertEqual(document["name"], "Curated")
        self.assertEqual(document["description"], "Local description")
        self.assertEqual(document["metadata"]["localized"]["en-US"]["title"], "Film")

    def test_lookup_search_receives_all_configured_languages(self):
        library.save_library_settings({"languages": ["es-ES", "de-DE", "en-US"]})
        with patch("apps.vod.library.tmdb_client") as factory:
            factory.return_value.search_candidates.return_value = []
            response = self.client.post(
                self.endpoint("tmdb-lookup"),
                {
                    "content_type": "movie",
                    "query": "Film",
                    "year": 2020,
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        factory.return_value.search_candidates.assert_called_once_with(
            "Film", 2020, "movie", ["es-ES", "de-DE", "en-US"]
        )

    def test_editor_saves_tmdb_assignment_and_manual_values_together(self):
        with patch("apps.vod.library.tmdb_client") as factory:
            factory.return_value.details.return_value = self.metadata()
            response = self.client.patch(
                self.endpoint("content"),
                {
                    "content_type": "movie",
                    "id": self.movie.pk,
                    "tmdb_id": "123",
                    "display_name": "Curated title",
                    "metadata": {"director": "Curated director"},
                },
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        self.movie.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.source.movie_id, self.movie.pk)
        self.assertEqual(self.movie.tmdb_match_id, "123")
        self.assertEqual(self.movie.display_name, "Curated title")
        self.assertEqual(self.movie.tmdb_metadata["director"], "Curated director")
        self.assertTrue(self.movie.tmdb_lookup_excluded)

    def test_invalid_editor_draft_rolls_back_tmdb_assignment_and_identity_merge(self):
        donor = Movie.objects.create(name="Existing title", tmdb_id="123")
        with patch("apps.vod.library.tmdb_client") as factory:
            factory.return_value.details.return_value = self.metadata()
            response = self.client.patch(
                self.endpoint("content"),
                {
                    "content_type": "movie",
                    "id": self.movie.pk,
                    "tmdb_id": "123",
                    "year": 2020,
                    "metadata": {"release_date": "2021-01-01"},
                },
                format="json",
            )
        self.assertEqual(response.status_code, 400)
        self.movie.refresh_from_db()
        self.source.refresh_from_db()
        self.assertTrue(Movie.objects.filter(pk=donor.pk).exists())
        self.assertFalse(self.movie.tmdb_match_id)
        self.assertEqual(self.source.movie_id, self.movie.pk)

    def test_invalid_editor_tmdb_id_is_rejected_before_lookup(self):
        with patch("apps.vod.library.tmdb_client") as factory:
            response = self.client.patch(
                self.endpoint("content"),
                {
                    "content_type": "movie",
                    "id": self.movie.pk,
                    "tmdb_id": "invalid",
                },
                format="json",
            )
        self.assertEqual(response.status_code, 400)
        factory.assert_not_called()

    def test_provider_identity_merges_preserve_library_edits(self):
        from apps.vod.identity import handle_identity_conflicts

        donor = Movie.objects.create(
            name="Matched donor",
            tmdb_id="123",
            display_name="Curated",
            tmdb_lookup_excluded=True,
            tmdb_metadata={
                "_manual_overrides": {"localized": {"en-US": {"overview": "Retained"}}}
            },
        )
        content, _ = handle_identity_conflicts(self.movie, None, "123", None)
        self.assertFalse(Movie.objects.filter(pk=donor.pk).exists())
        self.assertEqual(content.display_name, "Curated")
        self.assertEqual(library.canonical_document(content)["description"], "Retained")
        self.assertTrue(content.tmdb_lookup_excluded)

    def test_conflicting_manual_overrides_abort_provider_merges(self):
        from apps.vod.identity import handle_identity_conflicts

        self.movie.tmdb_metadata = {"_manual_overrides": {"release_date": "2020-01-01"}}
        self.movie.save()
        donor = Movie.objects.create(
            name="Donor",
            tmdb_id="123",
            tmdb_metadata={"_manual_overrides": {"release_date": "2021-01-01"}},
        )
        with self.assertRaises(ValueError):
            handle_identity_conflicts(self.movie, None, "123", None)
        self.assertTrue(Movie.objects.filter(pk=donor.pk).exists())

    def test_adult_metadata_cannot_bypass_the_existing_user_policy(self):
        content = library.apply_tmdb(self.movie, self.metadata(adult=True))
        self.assertTrue(content.is_adult)
        self.user.custom_properties = {"hide_adult_content": True}
        self.user.save()
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(self.endpoint()).json()["count"], 0)

    def test_existing_browse_endpoints_show_library_overlays(self):
        self.movie.display_name = "Curated title"
        self.movie.tmdb_poster_url = "https://image.tmdb.org/t/p/w500/test.jpg"
        self.movie.save()
        for name in ("movie-list", "unified-content-list"):
            response = self.client.get(
                reverse(f"api:vod:{name}"), {"search": "Curated"}
            )
            self.assertEqual(response.status_code, 200, name)
            item = response.json()["results"][0]
            self.assertEqual(item["name"], "Curated title")
            self.assertIn("kind=tmdb_poster", item["logo"]["cache_url"])
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.name, "NF - Film (2020)")

    def test_source_view_can_be_scoped_to_one_canonical_title(self):
        other = Movie.objects.create(name="Other")
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=other, stream_id="other"
        )
        response = self.client.get(
            self.endpoint(),
            {"view": "sources", "type": "movie", "content_id": self.movie.pk},
        ).json()
        self.assertEqual(response["count"], 1)
        self.assertEqual(response["results"][0]["source_id"], self.source.pk)

    def test_series_artwork_overlay_keeps_the_existing_cover_shape(self):
        from apps.vod.serializers import SeriesProviderInfoCoverSerializer

        series = Series.objects.create(
            name="Series",
            display_name="Curated",
            tmdb_poster_url="https://image.tmdb.org/t/p/w500/test.jpg",
        )
        response = library.overlay_provider_document({"cover": None}, series, None)
        cover = SeriesProviderInfoCoverSerializer(response["cover"]).data
        self.assertEqual(cover["name"], "Curated")
        self.assertIn("kind=tmdb_poster", cover["cache_url"])

    def test_browse_sorting_uses_the_visible_library_title(self):
        self.movie.display_name = "ZZZ"
        self.movie.save()
        other = Movie.objects.create(name="Z provider", display_name="AAA")
        M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=other, stream_id="different"
        )
        for name in ("movie-list", "unified-content-list"):
            result = self.client.get(reverse(f"api:vod:{name}")).json()["results"]
            self.assertEqual([item["name"] for item in result], ["AAA", "ZZZ"])

    def test_invalid_manual_ratings_are_rejected(self):
        for rating in ("invalid", "NaN", "-1", "11"):
            response = self.client.patch(
                self.endpoint("content"),
                {"content_type": "movie", "id": self.movie.pk, "rating": rating},
                format="json",
            )
            self.assertEqual(response.status_code, 400)

    def test_source_override_can_be_cleared_or_inherited(self):
        url = self.endpoint("source-metadata")
        ref = [{"content_type": "movie", "id": self.source.pk}]
        for value, expected in (([], []), (None, ["eng"])):
            self.assertEqual(
                self.client.patch(
                    url,
                    {"items": ref, "manual_metadata": {"audio_languages": value}},
                    format="json",
                ).status_code,
                200,
            )
            result = self.client.get(self.endpoint(), {"view": "sources"}).json()[
                "results"
            ][0]
            self.assertEqual(
                result["effective_metadata"]["values"]["audio_languages"], expected
            )

    def test_reassigning_a_wrong_source_preserves_old_public_ids(self):
        self.movie.tmdb_id = "999"
        self.movie.save()
        old_id, old_uuid = self.movie.pk, self.movie.uuid
        result = library.move_source_to_tmdb("movie", self.source.pk, self.metadata())
        self.source.refresh_from_db()
        self.assertEqual(self.source.movie_id, result.pk)
        self.assertEqual(result.tmdb_id, "123")
        self.assertEqual(resolve_content("movie", old_id)[0].pk, result.pk)
        self.assertEqual(
            resolve_content("movie", old_uuid, by_uuid=True)[0].pk, result.pk
        )

    def test_conflicting_episode_ids_abort_source_reassignment(self):
        current = Series.objects.create(name="Old", tmdb_id="999")
        target = Series.objects.create(name="New", tmdb_id="123")
        relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=current, external_series_id="old"
        )
        old = Episode.objects.create(
            series=current, name="Old", season_number=1, episode_number=1, tmdb_id="11"
        )
        Episode.objects.create(
            series=target, name="New", season_number=1, episode_number=1, tmdb_id="22"
        )
        source = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=old,
            series_relation=relation,
            stream_id="episode",
        )
        with self.assertRaises(ValueError):
            library.move_source_to_tmdb("series", relation.pk, self.metadata())
        source.refresh_from_db()
        self.assertEqual(source.episode_id, old.pk)
        relation.refresh_from_db()
        self.assertEqual(relation.series_id, current.pk)

    def test_source_reassignment_does_not_delete_unbound_episode_records(self):
        current = Series.objects.create(name="Old series", tmdb_id="999")
        relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=current, external_series_id="old"
        )
        orphan = Episode.objects.create(
            series=current, name="Unbound episode", season_number=1, episode_number=99
        )
        target = library.move_source_to_tmdb("series", relation.pk, self.metadata())
        self.assertNotEqual(target.pk, current.pk)
        self.assertTrue(Episode.objects.filter(pk=orphan.pk).exists())
        self.assertTrue(Series.objects.filter(pk=current.pk).exists())

    def test_category_cleanup_preserves_other_category_properties(self):
        relation = M3UVODCategoryRelation.objects.get(
            m3u_account=self.account, category=self.category
        )
        relation.custom_properties = {"marker": "retained"}
        relation.save()
        response = self.client.patch(
            self.endpoint("category-cleanup"),
            {
                "account": self.account.pk,
                "category": self.category.pk,
                "title_cleanup": {"pattern": "^NF - "},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        relation.refresh_from_db()
        self.assertEqual(relation.custom_properties["marker"], "retained")
        result = self.client.get(self.endpoint(), {"view": "sources"}).json()[
            "results"
        ][0]
        self.assertEqual(result["title_cleanup"]["pattern"], "^NF -")

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_authentication_failure_stops_without_locking_unprocessed_titles(
        self, _publish
    ):
        from apps.vod.tmdb import TMDBAuthenticationError

        library.save_library_settings({"api_token": "test", "match_missing": True})
        state = library.queue_library_job("enrich", [("movie", self.movie.pk)])
        with patch("apps.vod.library.tmdb_client") as factory:
            factory.return_value.search_outcome.side_effect = TMDBAuthenticationError(
                "Invalid token"
            )
            library.run_library_job(state["task_id"])
        state = VODMetadataState.objects.get(pk=1)
        self.assertEqual(state.status, "failed")
        self.assertEqual(state.progress["processed"], 0)
        self.movie.refresh_from_db()
        self.assertFalse(self.movie.tmdb_lookup_excluded)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_resume_only_queues_unprocessed_selection(self, _publish):
        state = VODMetadataState.objects.create(
            status="cancelled",
            selection=[["movie", 999], ["movie", self.movie.pk]],
            progress={"operation": "cleanup", "processed": 1},
        )
        response = self.client.post(self.endpoint("resume-job"), {}, format="json")
        self.assertEqual(response.status_code, 202)
        state.refresh_from_db()
        self.assertEqual(state.selection, [["movie", self.movie.pk]])
        self.assertEqual(state.progress["processed"], 0)
