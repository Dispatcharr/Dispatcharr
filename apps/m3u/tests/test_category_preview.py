"""Targeted preview payloads must stay private, temporary and import-safe."""

from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.category_preview import (
    MAX_IMPORT_MISSES,
    _key,
    _store_rows,
    cached_preview,
    import_cached_categories,
    remember_categories,
)
from apps.m3u.group_rules import CategoryImportMap
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import collect_xc_streams
from apps.vod.models import (
    Movie,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    VODCategory,
)
from apps.vod.tasks import refresh_movies, refresh_series, cleanup_orphaned_vod_content
from django.utils import timezone


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class CategoryPreviewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.account = M3UAccount.objects.create(
            name="Preview",
            account_type="XC",
            server_url="https://provider.invalid",
            username="preview-user",
            password="preview-secret",
            custom_properties={"enable_vod": True},
        )
        self.group = ChannelGroup.objects.create(name="News")
        self.live = ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account,
            channel_group=self.group,
            enabled=False,
            custom_properties={"xc_id": "10"},
        )
        self.movie = VODCategory.objects.create(name="Movies", category_type="movie")
        self.relation = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.movie,
            enabled=False,
            custom_properties={"note": "untouched"},
            metadata_defaults={"audio_languages": ["ger"]},
        )
        self.client = APIClient()
        self.client.force_authenticate(
            get_user_model().objects.create_user(
                username="preview-admin",
                user_level=10,
            )
        )
        self.url = f"/api/m3u/accounts/{self.account.pk}/group-rules/"
        self.provider = Mock()
        self.provider.__enter__ = Mock(return_value=self.provider)
        self.provider.__exit__ = Mock(return_value=False)
        self.provider.get_live_category_streams.return_value = self.rows("10")
        self.provider.get_vod_categories.return_value = [
            {"category_id": "20", "category_name": "Movies"}
        ]
        self.provider.get_vod_streams.return_value = self.rows("20")
        factory = patch("apps.m3u.category_preview.Client", return_value=self.provider)
        self.factory = factory.start()
        self.addCleanup(factory.stop)
        agent = patch.object(
            M3UAccount, "get_user_agent_string", return_value="Preview-Test"
        )
        agent.start()
        self.addCleanup(agent.stop)

    def rows(self, provider_id, name="Preview title"):
        return [
            {
                "category_id": provider_id,
                "stream_id": "123",
                "name": name,
                "container_extension": "mkv",
            }
        ]

    def post(self, scope="movie", group_id=None, query=""):
        return self.client.post(
            self.url + "load-content-preview/" + query,
            {
                "scope": scope,
                "group_id": group_id or self.movie.pk,
            },
            format="json",
        )

    def test_get_is_read_only_and_offers_targeted_load_without_contacting_provider(
        self,
    ):
        response = self.client.get(
            self.url + f"content-preview/?scope=movie&group_id={self.movie.pk}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["can_load_provider"])
        self.assertEqual(response.data["content_source"], "imported")
        self.factory.assert_not_called()

    def test_explicit_preview_fetches_only_this_category_and_does_not_import_or_save(
        self,
    ):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content_source"], "provider")
        self.assertEqual(response.data["results"][0]["name"], "Preview title")
        self.assertEqual(response.data["results"][0]["relation_id"], 0)
        self.provider.get_vod_streams.assert_called_once_with(category_id="20")
        self.assertFalse(Movie.objects.exists())
        self.assertFalse(M3UMovieRelation.objects.exists())
        self.relation.refresh_from_db()
        self.assertFalse(self.relation.enabled)
        self.assertEqual(self.relation.custom_properties, {"note": "untouched"})
        self.assertEqual(self.relation.metadata_defaults, {"audio_languages": ["ger"]})
        self.assertNotIn("preview-secret", str(response.data))

    def test_live_preview_uses_saved_provider_id_without_category_discovery(self):
        self.assertEqual(self.post("live", self.group.pk).status_code, 200)
        self.provider.get_live_category_streams.assert_called_once_with(
            category_id="10"
        )
        self.provider.get_live_categories.assert_not_called()
        self.assertFalse(Stream.objects.exists())
        self.live.refresh_from_db()
        self.assertFalse(self.live.enabled)

    def test_reopen_search_pagination_and_repeat_load_reuse_one_cached_payload(self):
        self.provider.get_vod_streams.return_value = self.rows(
            "20", "Zulu"
        ) + self.rows("20", "Alpha")
        self.assertEqual(self.post().data["count"], 2)
        again = self.post()
        self.assertEqual(again.data["count"], 2)
        result = self.client.get(
            self.url
            + f"content-preview/?scope=movie&group_id={self.movie.pk}&search=alpha&page_size=1"
        )
        self.assertEqual(result.data["count"], 1)
        self.assertEqual(result.data["results"][0]["name"], "Alpha")
        self.provider.get_vod_streams.assert_called_once_with(category_id="20")
        self.assertEqual(self.factory.call_count, 1)

    def test_cache_expires_and_connection_changes_cannot_reuse_old_payloads(self):
        self.post()
        self.assertIsNotNone(cached_preview(self.account, "movie", self.relation))
        for field in (
            "server_url",
            "username",
            "password",
            "user_agent_id",
            "account_type",
        ):
            with self.subTest(field=field):
                old = getattr(self.account, field)
                setattr(
                    self.account,
                    field,
                    999 if field == "user_agent_id" else "different",
                )
                self.assertIsNone(cached_preview(self.account, "movie", self.relation))
                setattr(self.account, field, old)
                self.assertIsNotNone(
                    cached_preview(self.account, "movie", self.relation)
                )
        key = _key(self.account, "movie", "index")
        self.assertNotIn("preview-secret", key)
        self.assertNotIn("preview-user", key)
        with patch.object(
            M3UAccount, "get_user_agent_string", return_value="Changed-Agent"
        ):
            self.assertIsNone(cached_preview(self.account, "movie", self.relation))
        with patch("django.core.cache.backends.locmem.time.time", return_value=10**12):
            self.assertIsNone(cached_preview(self.account, "movie", self.relation))

    def test_series_preview_and_import_reuse_the_same_category_payload(self):
        category = VODCategory.objects.create(name="Shows", category_type="series")
        relation = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account, category=category, enabled=True
        )
        remember_categories(
            self.account, "series", [{"category_id": "30", "category_name": "Shows"}]
        )
        self.provider.get_series.return_value = [
            {"category_id": "30", "series_id": "456", "name": "Preview show"}
        ]
        self.assertEqual(self.post("series", category.pk).data["count"], 1)
        importer = Mock()
        categories = CategoryImportMap({"30": category})
        categories.group_names = {"30": "Shows"}
        self.assertIsNone(
            refresh_series(importer, self.account, categories, {category.pk: relation})
        )
        importer.get_series.assert_not_called()
        self.assertTrue(
            M3USeriesRelation.objects.filter(
                m3u_account=self.account, external_series_id="456"
            ).exists()
        )

    def test_imported_preview_takes_precedence_without_provider_request(self):
        source = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            category=self.movie,
            stream_id="existing",
            movie=Movie.objects.create(name="Imported"),
        )
        _store_rows(self.account, "movie", "20", self.rows("20"))
        response = self.client.get(
            self.url + f"content-preview/?scope=movie&group_id={self.movie.pk}"
        )
        self.assertEqual(response.data["content_source"], "imported")
        self.assertFalse(response.data["can_load_provider"])
        self.assertEqual(response.data["results"][0]["relation_id"], source.pk)
        self.factory.assert_not_called()

    def test_uncategorized_import_keeps_full_catalog_fetch(self):
        self.post()
        self.relation.enabled = True
        self.relation.save(update_fields=["enabled"])
        uncategorized = VODCategory.objects.create(
            name="Uncategorized", category_type="movie"
        )
        selection = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account, category=uncategorized, enabled=True
        )
        importer = Mock()
        importer.get_vod_streams.return_value = []
        with patch("apps.vod.tasks.process_movie_batch"):
            refresh_movies(
                importer,
                self.account,
                {"20": self.movie},
                {self.movie.pk: self.relation, uncategorized.pk: selection},
            )
        importer.get_vod_streams.assert_called_once_with()

    def test_same_provider_id_cannot_cross_account_or_content_type(self):
        _store_rows(self.account, "live", "20", self.rows("20", "Live only"))
        other = M3UAccount.objects.create(
            name="Separate account",
            account_type="XC",
            server_url=self.account.server_url,
            username=self.account.username,
            password=self.account.password,
        )
        self.assertIsNone(import_cached_categories(other, "live", ["20"], Mock()))
        self.assertIsNone(
            import_cached_categories(self.account, "movie", ["20"], Mock())
        )

    def test_inflight_load_is_rejected_without_a_second_provider_request(self):
        cache.set(_key(self.account, "movie", f"loading:{self.relation.pk}"), True, 180)
        self.assertEqual(self.post().status_code, 400)
        self.factory.assert_not_called()

    def test_corrupt_cache_is_discarded_and_can_be_loaded_again(self):
        self.post()
        cache.set(_key(self.account, "movie", "rows:20"), b"broken-gzip", 900)
        self.assertIsNone(cached_preview(self.account, "movie", self.relation))
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.provider.get_vod_streams.call_count, 2)

    def test_cache_outage_does_not_break_regular_import_fallback(self):
        with patch(
            "apps.m3u.category_preview.cache.get",
            side_effect=RuntimeError("Cache unavailable"),
        ):
            self.assertIsNone(
                import_cached_categories(self.account, "movie", ["20"], Mock())
            )

    def test_cached_import_keeps_the_previous_full_provider_total(self):
        self.post()
        self.account.custom_properties["vod_catalog_counts"] = {
            "movies": {"provider_total": 12345}
        }
        self.relation.enabled = True
        categories = CategoryImportMap({"20": self.movie})
        importer = Mock()
        self.assertEqual(
            refresh_movies(
                importer, self.account, categories, {self.movie.pk: self.relation}
            ),
            12345,
        )
        importer.get_vod_streams.assert_not_called()

    def test_duplicate_category_names_keep_all_provider_ids_separate(self):
        remember_categories(
            self.account,
            "movie",
            [
                {"category_id": "20", "category_name": "Movies"},
                {"category_id": "21", "category_name": "Movies"},
            ],
        )
        self.provider.get_vod_streams.side_effect = lambda category_id: self.rows(
            category_id
        )
        self.assertEqual(self.post().data["count"], 2)
        self.assertEqual(self.provider.get_vod_streams.call_count, 2)
        self.provider.get_vod_categories.assert_not_called()

    def test_provider_ignoring_category_filter_is_rejected_and_not_cached(self):
        self.provider.get_vod_streams.return_value = self.rows("wrong")
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(cached_preview(self.account, "movie", self.relation))

    def test_empty_category_is_cached_without_importing(self):
        self.provider.get_vod_streams.return_value = []
        self.assertEqual(self.post().data["count"], 0)
        self.assertEqual(self.post().data["count"], 0)
        self.provider.get_vod_streams.assert_called_once()
        self.assertEqual(cached_preview(self.account, "movie", self.relation), [])

    def test_provider_errors_do_not_expose_credentials_or_cache_partial_data(self):
        self.provider.get_vod_streams.side_effect = RuntimeError(
            "https://provider.invalid/?password=preview-secret"
        )
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("preview-secret", str(response.data))
        self.assertNotIn("provider.invalid", str(response.data))
        self.assertIsNone(cached_preview(self.account, "movie", self.relation))

    def test_wrong_account_scope_invalid_id_and_non_admin_never_contact_provider(self):
        other = M3UAccount.objects.create(name="Other", account_type="XC")
        url = f"/api/m3u/accounts/{other.pk}/group-rules/load-content-preview/"
        self.assertEqual(
            self.client.post(
                url, {"scope": "movie", "group_id": self.movie.pk}, format="json"
            ).status_code,
            404,
        )
        self.assertEqual(self.post("series").status_code, 404)
        self.assertEqual(self.post(group_id=999999).status_code, 404)
        self.client.force_authenticate(
            get_user_model().objects.create_user(username="viewer", user_level=0)
        )
        self.assertEqual(self.post().status_code, 403)
        self.factory.assert_not_called()

    def test_standard_disabled_account_and_vod_disabled_cannot_load(self):
        for values in (
            {"account_type": "STD"},
            {"is_active": False},
            {"custom_properties": {"enable_vod": False}},
        ):
            with self.subTest(values=values):
                M3UAccount.objects.filter(pk=self.account.pk).update(**values)
                self.assertEqual(self.post().status_code, 400)
                M3UAccount.objects.filter(pk=self.account.pk).update(
                    account_type="XC",
                    is_active=True,
                    custom_properties={"enable_vod": True},
                )
        self.factory.assert_not_called()

    def test_import_reuses_payload_and_fetches_only_other_selected_categories(self):
        self.post()
        importer = Mock()
        importer.get_vod_streams.return_value = self.rows("21", "Other title")
        rows = import_cached_categories(self.account, "movie", ["20", "21"], importer)
        self.assertEqual(
            [row["name"] for row in rows], ["Preview title", "Other title"]
        )
        importer.get_vod_streams.assert_called_once_with(category_id="21")
        self.assertIsNone(cached_preview(self.account, "movie", self.relation))

    def test_no_cache_many_misses_and_category_errors_keep_full_refresh_fallback(self):
        importer = Mock()
        self.assertIsNone(
            import_cached_categories(self.account, "movie", ["20"], importer)
        )
        importer.get_vod_streams.assert_not_called()
        self.post()
        ids = ["20"] + [str(100 + index) for index in range(MAX_IMPORT_MISSES + 1)]
        self.assertIsNone(
            import_cached_categories(self.account, "movie", ids, importer)
        )
        importer.get_vod_streams.assert_not_called()
        importer.get_vod_streams.side_effect = RuntimeError("Unavailable")
        self.assertIsNone(
            import_cached_categories(self.account, "movie", ["20", "21"], importer)
        )

    def test_actual_movie_import_reuses_preview_and_preserves_other_enabled_category(
        self,
    ):
        self.post()
        self.relation.enabled = True
        self.relation.save(update_fields=["enabled"])
        other_category = VODCategory.objects.create(
            name="Other movies", category_type="movie"
        )
        other_selection = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account, category=other_category, enabled=True
        )
        other_source = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            category=other_category,
            stream_id="other",
            movie=Movie.objects.create(name="Other title"),
        )
        importer = Mock()
        importer.get_vod_streams.return_value = [
            {"category_id": "21", "stream_id": "other", "name": "Other title"}
        ]
        categories = CategoryImportMap({"20": self.movie, "21": other_category})
        categories.group_names = {"20": "Movies", "21": "Other movies"}
        start = timezone.now()
        provider_total = refresh_movies(
            importer,
            self.account,
            categories,
            {self.movie.pk: self.relation, other_category.pk: other_selection},
            scan_start_time=start,
        )
        cleanup_orphaned_vod_content(account_id=self.account.pk, scan_start_time=start)
        self.assertIsNone(provider_total)
        importer.get_vod_streams.assert_called_once_with(category_id="21")
        self.assertTrue(M3UMovieRelation.objects.filter(pk=other_source.pk).exists())
        source = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="123")
        self.assertEqual(source.container_extension, "mkv")
        self.assertEqual(
            source.effective_metadata()["values"]["audio_languages"], ["ger"]
        )
        self.assertIsNone(categories.catalog_stage)

    def test_live_import_reuses_raw_preview_and_retains_existing_stream_conversion(
        self,
    ):
        self.post("live", self.group.pk)
        with patch("apps.m3u.tasks.XCClient", return_value=self.provider):
            rows, provider_total = collect_xc_streams(
                self.account.pk, {"News": {"xc_id": "10"}}, include_provider_total=True
            )
        self.provider.get_all_live_streams.assert_not_called()
        self.assertIsNone(provider_total)
        self.assertEqual(rows[0]["name"], "Preview title")
        self.assertEqual(rows[0]["attributes"]["category_id"], "10")
        self.assertTrue(rows[0]["url"].endswith("/123.ts"))
