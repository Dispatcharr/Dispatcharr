"""Library details never mix canonical edits with concrete provider sources."""

import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.http import HttpResponse
from django.test import TestCase, override_settings

from apps.vod import library
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODContentAlias,
)
from apps.vod.presentation import canonical_title
from apps.vod.tests import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryPreviewTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint

    def details(self, **kwargs):
        return self.client.get(
            self.endpoint("details"),
            {
                "content_type": "movie",
                "id": self.movie.pk,
                **kwargs,
            },
        )

    def test_details_are_read_only_and_keep_provider_data_separate(self):
        library.save_library_settings({"languages": ["de-DE", "en-US", "es-ES"]})
        self.source.custom_properties = {
            "basic_data": {"name": "Provider Film", "plot": "Raw plot", "year": 2019},
            "detailed_info": {"director": "Provider Director", "duration_secs": 100},
            "direct_source": "https://private.example/secret",
            "username": "private-user",
            "password": "private-password",
        }
        self.source.save()
        library.update_content(
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "display_name": "Library Film",
                "description": "Edited description",
                "metadata": {
                    "runtime_minutes": 120,
                    "director": "",
                    "localized": {
                        "de-DE": {"title": "Film DE", "overview": "Deutsch"},
                        "es-ES": {"title": "Film ES", "overview": "Español"},
                    },
                    "external_ids": {"imdb_id": "tt123"},
                },
            }
        )
        before = self.source.custom_properties.copy()
        with patch("apps.vod.provider_refresh.queue_provider_refresh") as refresh:
            response = self.details()
        self.assertEqual(response.status_code, 200)
        refresh.assert_not_called()
        document = response.json()
        canonical = document["canonical"]
        self.assertEqual(canonical["name"], "Library Film")
        self.assertEqual(canonical["duration_secs"], 7200)
        self.assertEqual(canonical["imdb_id"], "tt123")
        self.assertEqual(canonical["metadata"]["director"], "")
        self.assertEqual(canonical["metadata_languages"], ["de-DE", "en-US", "es-ES"])
        provider = document["sources"][0]["provider"]
        self.assertEqual(provider["name"], "Provider Film")
        self.assertEqual(provider["description"], "Raw plot")
        self.assertEqual(provider["director"], "Provider Director")
        self.assertEqual(provider["duration_secs"], 100)
        self.assertEqual(provider["year"], 2019)
        for secret in (
            "private-user",
            "private-password",
            "private.example",
            "server_url",
        ):
            self.assertNotIn(secret, str(document))
        self.source.refresh_from_db()
        self.assertEqual(self.source.custom_properties, before)

    def test_source_selection_is_exact_and_rejects_foreign_sources(self):
        other = M3UMovieRelation.objects.create(
            movie=self.movie,
            m3u_account=self.account,
            stream_id="11",
            custom_properties={"basic_data": {"name": "Second variant"}},
        )
        result = self.details(source_id=other.pk).json()
        self.assertEqual(result["selected_source_id"], other.pk)
        self.assertEqual(len(result["sources"]), 2)
        self.assertEqual(self.details(source_id=other.pk + 100).status_code, 404)
        self.assertEqual(self.details(unexpected=True).status_code, 400)

    def test_account_filter_prefers_a_source_without_excluding_other_sources(self):
        from apps.m3u.models import M3UAccount

        account = M3UAccount.objects.create(
            name="Other provider", account_type="XC", is_active=True
        )
        other = M3UMovieRelation.objects.create(
            movie=self.movie, m3u_account=account, stream_id="20"
        )
        result = self.details(preferred_account=account.pk).json()
        self.assertEqual(result["selected_source_id"], other.pk)
        self.assertEqual(
            {row["source_id"] for row in result["sources"]}, {self.source.pk, other.pk}
        )
        self.assertEqual(
            self.details(preferred_account=account.pk, source_id=self.source.pk).json()[
                "selected_source_id"
            ],
            self.source.pk,
        )
        self.assertEqual(
            self.details(preferred_account=account.pk + 100).json()[
                "selected_source_id"
            ],
            self.source.pk,
        )
        self.assertEqual(self.details(preferred_account="invalid").status_code, 400)

    def test_provider_artwork_is_source_exact_proxied_and_read_only(self):
        self.source.custom_properties = {
            "basic_data": {
                "stream_icon": "https://private.example/first-poster.jpg",
                "backdrop_path": ["https://private.example/first-backdrop.jpg"],
            }
        }
        self.source.save()
        other = M3UMovieRelation.objects.create(
            movie=self.movie,
            m3u_account=self.account,
            stream_id="11",
            custom_properties={
                "basic_data": {
                    "stream_icon": "https://private.example/second-poster.jpg",
                    "backdrop_path": ["https://private.example/second-backdrop.jpg"],
                }
            },
        )
        self.movie.tmdb_poster_url = "https://private.example/tmdb-poster.jpg"
        self.movie.tmdb_backdrop_url = "https://private.example/tmdb-backdrop.jpg"
        self.movie.save()
        before = self.source.custom_properties.copy()
        with patch("apps.vod.provider_refresh.queue_provider_refresh") as refresh:
            result = self.details(source_id=other.pk).json()
        refresh.assert_not_called()
        self.assertNotIn("private.example", str(result))
        self.assertIn("kind=tmdb_backdrop", result["canonical"]["backdrop_url"])
        self.assertEqual(
            result["canonical"]["metadata"]["backdrop_url"],
            result["canonical"]["backdrop_url"],
        )
        for row in result["sources"]:
            for field in ("poster_url", "backdrop_url"):
                query = parse_qs(urlsplit(row["provider"][field]).query)
                self.assertEqual(query["relation_id"], [str(row["source_id"])])
                self.assertEqual(query["m3u_account_id"], [str(self.account.pk)])
        url = urlsplit(result["sources"][1]["provider"]["poster_url"])
        with patch(
            "apps.vod.image_proxy.serve_vod_image",
            return_value=HttpResponse(b"image", content_type="image/png"),
        ) as serve:
            response = self.client.get(f"{url.path}?{url.query}")
        self.assertEqual(response.status_code, 200)
        serve.assert_called_once_with("https://private.example/second-poster.jpg")
        self.source.refresh_from_db()
        self.assertEqual(self.source.custom_properties, before)

    def test_exact_image_scope_rejects_wrong_parent_account_and_invalid_relations(self):
        from apps.vod.image_proxy import resolve_vod_image_url

        other_movie = Movie.objects.create(name="Other film")
        foreign = M3UMovieRelation.objects.create(
            movie=other_movie,
            m3u_account=self.account,
            stream_id="foreign",
            custom_properties={
                "basic_data": {"stream_icon": "https://private.example/foreign.jpg"}
            },
        )
        self.assertIsNone(
            resolve_vod_image_url(self.movie, "movie_image", relation_id=foreign.pk)
        )
        self.assertIsNone(
            resolve_vod_image_url(
                other_movie,
                "movie_image",
                m3u_account_id=self.account.pk + 100,
                relation_id=foreign.pk,
            )
        )
        for relation_id in (foreign.pk, "invalid", 0, -1):
            with patch("apps.vod.image_proxy.serve_vod_image") as serve:
                response = self.client.get(
                    f"/api/vod/movies/{self.movie.pk}/image/",
                    {"kind": "movie_image", "relation_id": relation_id},
                )
            self.assertEqual(response.status_code, 404)
            serve.assert_not_called()

    def test_disabled_types_adult_content_and_inactive_sources_are_unavailable(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.details().status_code, 200)
        self.user.custom_properties = {"vod_movies_enabled": False}
        self.user.save()
        self.assertEqual(self.details().status_code, 404)
        self.user.custom_properties = {"hide_adult_content": True}
        self.user.save()
        self.movie.is_adult = True
        self.movie.save()
        self.assertEqual(self.details().status_code, 404)
        self.client.force_authenticate(self.admin)
        self.account.is_active = False
        self.account.save()
        self.assertEqual(self.details().status_code, 404)

    def test_empty_title_with_a_match_clears_an_earlier_manual_title(self):
        library.save_library_settings({"languages": ["de-DE", "en-US"]})
        metadata = {
            "id": "4711",
            "original_title": "Original",
            "localized": {
                "de-DE": {"title": "Film DE"},
                "en-US": {"title": "Film EN"},
            },
        }
        payload = {"content_type": "movie", "id": self.movie.pk}
        library.update_content({**payload, "display_name": "Original"}, metadata)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.display_name, "Original")
        library.update_content({**payload, "display_name": ""}, metadata)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.display_name, "")
        self.assertEqual(
            canonical_title(self.movie, library.library_settings()["languages"]),
            "Film DE",
        )

    def test_runtime_and_explicit_clears_reach_compatible_provider_overlay(self):
        library.update_content(
            {
                "content_type": "movie",
                "id": self.movie.pk,
                "metadata": {
                    "runtime_minutes": None,
                    "director": "",
                    "country": "",
                    "release_date": None,
                    "external_ids": {"imdb_id": ""},
                },
            }
        )
        self.movie.refresh_from_db()
        result = library.overlay_provider_document(
            {
                "duration_secs": 99,
                "director": "Old",
                "country": "Old",
                "imdb_id": "tt999",
                "release_date": "2020-01-01",
            },
            self.movie,
            None,
        )
        self.assertIsNone(result["duration_secs"])
        for field in ("director", "country", "release_date", "imdb_id"):
            self.assertEqual(result[field], "")

    def test_series_episodes_are_source_exact_season_filtered_and_paginated(self):
        series = Series.objects.create(name="Series")
        source = M3USeriesRelation.objects.create(
            series=series, m3u_account=self.account, external_series_id="s1"
        )
        other = M3USeriesRelation.objects.create(
            series=series, m3u_account=self.account, external_series_id="s2"
        )
        for index, season in enumerate([0, 1, 1]):
            episode = Episode.objects.create(
                series=series,
                name=f"Episode {index}",
                season_number=season,
                episode_number=index,
                duration_secs=300,
            )
            M3UEpisodeRelation.objects.create(
                series_relation=source,
                m3u_account=self.account,
                episode=episode,
                stream_id=f"source-{index}",
                custom_properties={
                    "info": {
                        "title": f"Source episode {index}",
                        "info": {
                            "duration_secs": 123,
                            "plot": "Source plot",
                            "genre": "Documentary",
                            "director": "Source director",
                            "cast": ["Actor A", "Actor B"],
                            "bitrate": 2500,
                            "audio": {
                                "codec_name": "aac",
                                "channels": 2,
                                "password": "secret-audio",
                            },
                            "movie_image": "https://private.example/still.jpg",
                            "video": {"height": 1080, "codec_name": "h264"},
                        },
                    }
                },
            )
            M3UEpisodeRelation.objects.create(
                series_relation=other,
                m3u_account=self.account,
                episode=episode,
                stream_id=f"other-{index}",
            )
        params = {
            "content_type": "series",
            "id": series.pk,
            "source_id": source.pk,
            "season": 1,
            "page_size": 1,
            "page": 2,
        }
        result = self.client.get(self.endpoint("details"), params).json()
        self.assertEqual(result["episode_count"], 2)
        self.assertEqual(result["episode_page"], 2)
        self.assertEqual(
            result["seasons"], [{"number": 0, "count": 1}, {"number": 1, "count": 2}]
        )
        self.assertEqual(result["episodes"][0]["stream_id"], "source-2")
        self.assertEqual(result["episodes"][0]["name"], "Source episode 2")
        self.assertEqual(result["episodes"][0]["duration_secs"], 123)
        self.assertEqual(result["episodes"][0]["description"], "Source plot")
        self.assertEqual(result["episodes"][0]["resolution"], "1080p")
        self.assertEqual(result["episodes"][0]["video_codec"], "h264")
        self.assertEqual(result["selected_season"], 1)
        self.assertEqual(result["episodes"][0]["genre"], "Documentary")
        self.assertEqual(result["episodes"][0]["director"], "Source director")
        self.assertEqual(result["episodes"][0]["actors"], "Actor A, Actor B")
        self.assertEqual(
            result["episodes"][0]["technical"]["audio"],
            {"codec_name": "aac", "channels": 2},
        )
        self.assertNotIn("secret-audio", str(result))
        self.assertNotIn("private.example", result["episodes"][0]["poster_url"])
        self.assertIn("relation_id=", result["episodes"][0]["poster_url"])
        facts = {
            row["source_id"]: row["provider"]["technical"] for row in result["sources"]
        }
        self.assertEqual(facts[source.pk]["episode_resolutions"], ["1080p"])
        self.assertEqual(facts[source.pk]["episode_video_codecs"], ["h264"])
        self.assertEqual(facts.get(other.pk, {}).get("episode_video_codecs", []), [])
        result = self.client.get(
            self.endpoint("details"), {**params, "source_id": other.pk}
        ).json()
        self.assertEqual(result["episodes"][0]["stream_id"], "other-2")

    def series_inventory(self, seasons):
        series = Series.objects.create(name="Season test")
        source = M3USeriesRelation.objects.create(
            series=series, m3u_account=self.account, external_series_id="seasons"
        )
        for index, season in enumerate(seasons):
            episode = Episode.objects.create(
                series=series,
                name=f"Episode {index}",
                season_number=season,
                episode_number=index,
            )
            M3UEpisodeRelation.objects.create(
                series_relation=source,
                m3u_account=self.account,
                episode=episode,
                stream_id=str(index),
            )
        return {"content_type": "series", "id": series.pk, "source_id": source.pk}

    def test_series_defaults_to_first_available_season_without_mixing_seasons(self):
        params = self.series_inventory([2, 1, 1])
        with patch("apps.vod.provider_refresh.queue_provider_refresh") as refresh:
            result = self.client.get(self.endpoint("details"), params).json()
        refresh.assert_not_called()
        self.assertEqual(result["selected_season"], 1)
        self.assertEqual(result["episode_count"], 2)
        self.assertEqual({row["season_number"] for row in result["episodes"]}, {1})
        result = self.client.get(
            self.endpoint("details"), {**params, "season": 2}
        ).json()
        self.assertEqual(result["selected_season"], 2)
        self.assertEqual(result["episode_count"], 1)
        result = self.client.get(
            self.endpoint("details"), {**params, "season": 99}
        ).json()
        self.assertEqual(result["selected_season"], 1)

    def test_specials_and_unassigned_episodes_remain_accessible(self):
        params = self.series_inventory([None, 0, 1])
        result = self.client.get(self.endpoint("details"), params).json()
        self.assertEqual(result["selected_season"], 0)
        result = self.client.get(
            self.endpoint("details"), {**params, "season": -1}
        ).json()
        self.assertEqual(result["selected_season"], -1)
        self.assertEqual(result["episode_count"], 1)
        self.assertIsNone(result["episodes"][0]["season_number"])
        self.assertEqual(
            self.client.get(
                self.endpoint("details"), {**params, "season": -2}
            ).status_code,
            400,
        )

    def test_empty_series_has_no_selected_season(self):
        params = self.series_inventory([])
        result = self.client.get(self.endpoint("details"), params).json()
        self.assertIsNone(result["selected_season"])
        self.assertEqual(result["episode_count"], 0)

    def test_technical_projection_does_not_expose_arbitrary_provider_keys(self):
        self.source.custom_properties = {
            "detailed_info": {
                "video": {
                    "width": 1920,
                    "codec_name": "h264",
                    "private_url": "secret-video",
                },
                "audio": {"codec_name": "aac", "password": "secret-audio"},
            }
        }
        self.source.save()
        result = self.details().json()["sources"][0]["provider"]["technical"]
        self.assertEqual(result["video"], {"width": 1920, "codec_name": "h264"})
        self.assertEqual(result["audio"], {"codec_name": "aac"})

    def test_single_source_save_returns_current_canonical_title(self):
        response = self.client.patch(
            self.endpoint("source-metadata"),
            {
                "items": [{"content_type": "movie", "id": self.source.pk}],
                "manual_metadata": {"audio_languages": ["eng", "ger"]},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["metadata"]["id"], self.movie.pk)

    def test_existing_public_alias_resolves_to_the_current_title(self):
        VODContentAlias.objects.create(
            content_type="movie",
            legacy_id=999999,
            legacy_uuid=uuid.uuid4(),
            target_id=self.movie.pk,
        )
        response = self.details(id=999999)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["canonical"]["content_id"], self.movie.pk)
