"""Permanent source metadata and shared compact-output selection contract."""

from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_series_info, xc_get_vod_info, xc_get_vod_streams
from apps.proxy.vod_proxy.views import _get_content_and_relation
from apps.vod.language_codes import LANGUAGES
from apps.vod.metadata import (
    metadata_satisfies,
    normalize_language_code,
    update_declared_metadata,
    validate_source_metadata,
)
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
from apps.vod.references import output_reference
from apps.vod.selection import source_candidates
from apps.vod.tasks import process_movie_batch


class MetadataValidationTests(SimpleTestCase):
    def test_full_iso_catalogue_and_aliases(self):
        self.assertGreater(len(LANGUAGES), 480)
        for code, data in LANGUAGES.items():
            for alias in (code, data.get("alpha2"), data.get("terminological")):
                if alias:
                    self.assertEqual(normalize_language_code(alias.upper()), code)
        self.assertEqual(normalize_language_code("deu"), "ger")
        self.assertEqual(normalize_language_code("fra"), "fre")
        self.assertEqual(normalize_language_code("bod"), "tib")

    def test_multiple_languages_and_features_are_normalized(self):
        self.assertEqual(
            validate_source_metadata(
                {
                    "audio_languages": ["de", "ENG", "deu"],
                    "subtitle_languages": ["fra", "en"],
                    "video_features": ["HDR", "dv"],
                    "resolution": "4K",
                }
            ),
            {
                "audio_languages": ["ger", "eng"],
                "subtitle_languages": ["fre", "eng"],
                "video_features": ["hdr", "dv"],
                "resolution": "2160p",
            },
        )

    def test_invalid_values_are_rejected(self):
        for metadata in (
            {"audio_languages": "ger"},
            {"audio_languages": ["xx"]},
            {"subtitle_languages": [3]},
            {"video_features": ["anything"]},
            {"video_features": ["custom:"]},
            {"video_features": ["custom:bad tag"]},
            {"video_features": [3]},
            {"resolution": "very good"},
            {"provider_url": "https://example.invalid"},
        ):
            with self.subTest(metadata=metadata), self.assertRaises(ValueError):
                validate_source_metadata(metadata)

    def test_custom_features_and_numeric_resolutions_round_trip(self):
        self.assertEqual(
            validate_source_metadata(
                {
                    "video_features": [
                        "HDR",
                        "custom:IMAX",
                        "custom:imax",
                        "custom:hdr",
                    ],
                    "resolution": "360p",
                }
            ),
            {"video_features": ["hdr", "custom:imax"], "resolution": "360p"},
        )
        self.assertEqual(
            validate_source_metadata({"resolution": "SD"}), {"resolution": "SD"}
        )
        self.assertTrue(
            metadata_satisfies(
                {"video_features": ["hdr", "custom:imax"]},
                {"video_features": ["custom:imax"]},
            )
        )
        self.assertFalse(
            metadata_satisfies(
                {"video_features": ["hdr"]}, {"video_features": ["custom:imax"]}
            )
        )

    def test_empty_and_reset_are_distinct(self):
        self.assertEqual(
            validate_source_metadata({"audio_languages": []}), {"audio_languages": []}
        )
        self.assertEqual(
            validate_source_metadata({"audio_languages": None}, allow_reset=True),
            {"audio_languages": None},
        )

    def test_bilingual_source_can_satisfy_german_but_unknown_cannot(self):
        requirements = {
            "audio_languages": ["ger"],
            "resolution": "1080p",
            "video_features": ["hdr"],
        }
        self.assertTrue(
            metadata_satisfies(
                {
                    **requirements,
                    "audio_languages": ["ger", "eng"],
                },
                requirements,
            )
        )
        for metadata in (
            {},
            {**requirements, "audio_languages": ["eng"]},
            {**requirements, "resolution": "2160p"},
        ):
            self.assertFalse(metadata_satisfies(metadata, requirements))


class SourceMetadataTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Source A",
            account_type="XC",
            server_url="https://a.example.invalid",
            username="synthetic-user",
            password="synthetic-password",
            priority=10,
            custom_properties={"enable_vod": True},
        )
        self.other_account = M3UAccount.objects.create(
            name="Source B",
            account_type="XC",
            server_url="https://b.example.invalid",
            priority=1,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(name="Movies", category_type="movie")
        self.category_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account,
            category=self.category,
            enabled=True,
            metadata_defaults={"audio_languages": ["ger"], "resolution": "1080p"},
        )
        self.movie = Movie.objects.create(name="Shared Film", tmdb_id="123", year=2020)
        self.source = self.make_source(
            self.account, "1", {"audio_languages": ["ger"], "resolution": "1080p"}
        )
        self.other = self.make_source(
            self.other_account,
            "2",
            {"audio_languages": ["ger", "eng"], "resolution": "1080p"},
        )
        self.user = User.objects.create_user(
            username="metadata-admin", password="test", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def make_source(self, account, stream_id, metadata):
        return M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=self.movie,
            category=self.category,
            stream_id=stream_id,
            declared_metadata=metadata,
            custom_properties={"detailed_fetched": True},
            last_advanced_refresh=timezone.now(),
        )

    def test_source_metadata_does_not_create_a_second_content_identity(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Movie.objects.create(name="Other language", tmdb_id="123")
        self.assertEqual(self.movie.m3u_relations.count(), 2)

    def test_manual_empty_overrides_inherited_languages(self):
        self.source.manual_metadata = {"audio_languages": []}
        effective = self.source.effective_metadata()
        self.assertEqual(effective["values"]["audio_languages"], [])
        self.assertEqual(effective["provenance"]["audio_languages"], "manual")
        self.assertEqual(self.source.declared_metadata["audio_languages"], ["ger"])

    def test_provider_and_category_provenance_are_not_mixed(self):
        self.source.declared_metadata = {}
        effective = self.source.effective_metadata()
        self.assertEqual(effective["provenance"]["audio_languages"], "category")
        self.assertEqual(self.source.declared_metadata, {})

    def test_import_retains_manual_values_and_source_ids(self):
        self.source.manual_metadata = {
            "audio_languages": ["ger", "eng"],
            "video_features": ["hdr"],
        }
        self.source.save(update_fields=["manual_metadata"])
        before = self.movie.pk, self.source.pk
        process_movie_batch(
            self.account,
            [
                {
                    "name": "Shared Film",
                    "stream_id": "1",
                    "category_id": "9",
                    "tmdb_id": "123",
                    "audio_languages": ["fr"],
                    "resolution": "2160p",
                }
            ],
            {"9": self.category},
            {self.category.pk: self.category_relation},
        )
        self.source.refresh_from_db()
        self.assertEqual((self.source.movie_id, self.source.pk), before)
        self.assertEqual(self.source.declared_metadata["audio_languages"], ["fre"])
        self.assertEqual(
            self.source.effective_metadata()["values"]["audio_languages"],
            ["ger", "eng"],
        )

    def test_candidates_preserve_selected_language_and_resolution(self):
        english = self.make_source(
            self.other_account, "3", {"audio_languages": ["eng"], "resolution": "1080p"}
        )
        uhd = self.make_source(
            self.other_account, "4", {"audio_languages": ["ger"], "resolution": "2160p"}
        )
        eligible = source_candidates([self.source, self.other, english, uhd])
        self.assertEqual(
            [source.pk for source in eligible], [self.source.pk, self.other.pk]
        )

    def test_compact_output_is_one_entry_with_stable_source_requirements(self):
        request = RequestFactory().get("/player_api.php")
        rows = xc_get_vod_streams(request, self.user)
        self.assertEqual(len(rows), 1)
        public_id = rows[0]["stream_id"]
        self.assertIn("GER", rows[0]["name"])
        self.account.priority = 0
        self.account.save(update_fields=["priority"])
        self.other.declared_metadata = {
            "audio_languages": ["eng"],
            "resolution": "1080p",
        }
        self.other.save(update_fields=["declared_metadata"])
        info = xc_get_vod_info(request, self.user, public_id)
        self.assertIn("GER", info["info"]["name"])
        self.assertNotIn("ENG", info["info"]["name"])
        self.assertEqual(info["movie_data"]["stream_id"], public_id)

    def test_public_ids_never_collide_with_future_content_ids(self):
        ref = output_reference("movie", self.movie.pk, {"audio_languages": ["ger"]})
        repeated = output_reference("movie", self.movie.pk, {"audio_languages": ["de"]})
        self.assertEqual(ref.legacy_id, repeated.legacy_id)
        future = Movie.objects.create(name="Future Film")
        self.assertGreater(future.pk, max(ref.legacy_id, repeated.legacy_id))
        self.assertEqual(
            output_reference(
                "movie", self.movie.pk, {"audio_languages": ["ger"]}
            ).legacy_id,
            ref.legacy_id,
        )

    def test_playback_resolves_public_context_before_priority_selection(self):
        reference = output_reference(
            "movie", self.movie.pk, {"audio_languages": ["eng"], "resolution": "1080p"}
        )
        obj, selected, candidates = _get_content_and_relation(
            "movie", reference.legacy_uuid
        )
        self.assertEqual(obj.pk, self.movie.pk)
        self.assertEqual(selected.pk, self.other.pk)
        self.assertEqual([source.pk for source in candidates], [self.other.pk])

    def test_provider_stream_ids_are_scoped_to_account(self):
        self.other.stream_id = "1"
        self.other.save(update_fields=["stream_id"])
        obj, source, _ = _get_content_and_relation(
            "movie", self.movie.uuid, self.other_account.pk, "1"
        )
        self.assertEqual(source.pk, self.other.pk)

    def test_manual_metadata_api_validates_and_resets_only_requested_fields(self):
        url = f"/api/vod/movie-sources/{self.source.pk}/"
        response = self.client.patch(
            url,
            {
                "manual_metadata": {
                    "audio_languages": ["de", "en"],
                    "video_features": ["HDR"],
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.source.refresh_from_db()
        self.assertEqual(self.source.manual_metadata["audio_languages"], ["ger", "eng"])
        response = self.client.patch(
            url, {"manual_metadata": {"audio_languages": None}}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.source.refresh_from_db()
        self.assertNotIn("audio_languages", self.source.manual_metadata)
        self.assertEqual(self.source.manual_metadata["video_features"], ["hdr"])
        self.assertEqual(
            self.client.patch(
                url, {"declared_metadata": {}}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(
                url, {"manual_metadata": {"audio_languages": ["xx"]}}, format="json"
            ).status_code,
            400,
        )

    def test_category_defaults_are_validated_and_saved_without_identity_changes(self):
        response = self.client.patch(
            f"/api/m3u/accounts/{self.account.pk}/group-settings/",
            {
                "category_settings": [
                    {
                        "id": self.category.pk,
                        "enabled": True,
                        "metadata_defaults": {
                            "audio_languages": ["de", "en"],
                            "video_features": ["dv"],
                        },
                    }
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.category_relation.refresh_from_db()
        self.assertEqual(
            self.category_relation.metadata_defaults["audio_languages"], ["ger", "eng"]
        )
        self.assertEqual(
            self.category_relation.metadata_defaults["resolution"], "1080p"
        )
        self.assertTrue(Movie.objects.filter(pk=self.movie.pk).exists())

    def test_category_editor_custom_properties_save_typed_metadata(self):
        response = self.client.patch(
            f"/api/m3u/accounts/{self.account.pk}/group-settings/",
            {
                "category_settings": [
                    {
                        "id": self.category.pk,
                        "enabled": True,
                        "custom_properties": {
                            "audio_languages": ["ger", "eng"],
                            "subtitle_languages": [],
                            "resolution": "360p",
                            "video_features": ["hdr", "custom:imax"],
                        },
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.category_relation.refresh_from_db()
        self.assertEqual(
            self.category_relation.metadata_defaults,
            {
                "audio_languages": ["ger", "eng"],
                "subtitle_languages": [],
                "resolution": "360p",
                "video_features": ["hdr", "custom:imax"],
            },
        )

    def test_partial_provider_refresh_preserves_other_source_facts(self):
        self.source.declared_metadata["video_features"] = ["hdr"]
        update_declared_metadata(self.source, {"audio_languages": ["en"]})
        self.assertEqual(
            self.source.declared_metadata,
            {
                "audio_languages": ["eng"],
                "resolution": "1080p",
                "video_features": ["hdr"],
            },
        )

    def test_detail_refresh_cannot_silently_change_a_published_selection(self):
        reference = output_reference(
            "movie", self.movie.pk, {"audio_languages": ["ger"]}
        )
        self.source.last_advanced_refresh = None
        self.source.save(update_fields=["last_advanced_refresh"])

        def changed_provider_data(source_id):
            M3UMovieRelation.objects.filter(pk=source_id).update(
                declared_metadata={"audio_languages": ["eng"]},
            )

        with patch(
            "apps.vod.tasks.refresh_movie_advanced_data",
            side_effect=changed_provider_data,
        ):
            with self.assertRaises(Http404):
                xc_get_vod_info(
                    RequestFactory().get("/player_api.php"),
                    self.user,
                    reference.legacy_id,
                )

    def test_series_episode_ids_keep_the_selected_language(self):
        show = Series.objects.create(name="Shared show", tmdb_id="series-123")
        episode = Episode.objects.create(
            series=show, name="Episode", season_number=1, episode_number=1
        )
        for account, languages in (
            (self.account, ["ger"]),
            (self.other_account, ["eng"]),
        ):
            parent = M3USeriesRelation.objects.create(
                series=show,
                m3u_account=account,
                external_series_id="show",
                declared_metadata={"audio_languages": languages, "resolution": "1080p"},
                last_episode_refresh=timezone.now(),
                custom_properties={"episodes_fetched": True, "detailed_fetched": True},
            )
            M3UEpisodeRelation.objects.create(
                episode=episode,
                m3u_account=account,
                series_relation=parent,
                stream_id="same-episode-id",
            )
        reference = output_reference("series", show.pk, {"audio_languages": ["eng"]})
        info = xc_get_series_info(
            RequestFactory().get("/player_api.php"), self.user, reference.legacy_id
        )
        published_id = info["episodes"][1][0]["id"]
        from apps.vod.selection import resolve_content

        _, requirements = resolve_content("episode", published_id)
        self.assertEqual(requirements["audio_languages"], ["eng"])
        from apps.vod.models import VODContentAlias

        alias = VODContentAlias.objects.get(
            content_type="episode", legacy_id=published_id
        )
        _, selected, _ = _get_content_and_relation("episode", alias.legacy_uuid)
        self.assertEqual(selected.m3u_account_id, self.other_account.pk)

    def test_metadata_api_is_admin_only(self):
        viewer = User.objects.create_user(username="metadata-viewer", user_level=0)
        self.client.force_authenticate(viewer)
        for url in (
            "/api/vod/source-metadata-options/",
            f"/api/vod/movie-sources/{self.source.pk}/",
        ):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.patch(
                f"/api/vod/movie-sources/{self.source.pk}/",
                {"manual_metadata": {"audio_languages": ["en"]}},
                format="json",
            ).status_code,
            403,
        )

    def test_metadata_options_use_the_full_catalogue(self):
        response = self.client.get("/api/vod/source-metadata-options/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["languages"]), len(LANGUAGES))
        self.assertIn("360p", response.data["resolutions"])
        self.assertTrue(
            all(
                value.endswith("p") and value[:-1].isdigit()
                for value in response.data["resolutions"]
            )
        )
        self.assertIn(
            {"value": "ger", "label": "German (ger)"}, response.data["languages"]
        )


class SourceMetadataSchemaTests(SimpleTestCase):
    def test_new_endpoints_have_valid_openapi(self):
        from django.urls import path
        from drf_spectacular.generators import SchemaGenerator
        from drf_spectacular.validation import validate_schema
        from rest_framework.routers import SimpleRouter
        from apps.vod.api_views import (
            EpisodeSourceViewSet,
            MovieSourceViewSet,
            SeriesSourceViewSet,
            SourceMetadataOptionsView,
        )

        router = SimpleRouter()
        for name, view in (
            ("movie-sources", MovieSourceViewSet),
            ("series-sources", SeriesSourceViewSet),
            ("episode-sources", EpisodeSourceViewSet),
        ):
            router.register(name, view, basename=name)
        schema = SchemaGenerator(
            patterns=[
                path("source-metadata-options/", SourceMetadataOptionsView.as_view()),
                *router.urls,
            ]
        ).get_schema(public=True)
        validate_schema(schema)
        self.assertIn("/movie-sources/{id}/", schema["paths"])
        self.assertIn("patch", schema["paths"]["/movie-sources/{id}/"])
