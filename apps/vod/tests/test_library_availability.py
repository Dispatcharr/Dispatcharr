"""Canonical output blocks are independent of metadata protection and sources."""

from unittest.mock import patch
from uuid import uuid4

from django.http import Http404
from django.test import RequestFactory, TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.output.views import (
    xc_get_series,
    xc_get_series_categories,
    xc_get_series_info,
    xc_get_vod_categories,
    xc_get_vod_info,
    xc_get_vod_streams,
)
from apps.proxy.vod_proxy.views import (
    _get_content_and_relation,
    head_vod,
    stream_vod,
    stream_xc_episode,
    stream_xc_movie,
)
from apps.vod import library
from apps.vod.identity import remember_alias
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3USeriesRelation,
    Movie,
    Series,
)
from apps.vod.provider_metadata import reconcile_provider_metadata
from apps.vod.selection import source_candidates

from . import test_library as fixtures


class LibraryAvailabilityTests(TestCase):
    setUpBase = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint
    metadata = fixtures.LibraryTests.metadata

    def setUp(self):
        self.setUpBase()
        self.series = Series.objects.create(name="Series")
        self.series_source = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=self.series, external_series_id="20"
        )
        self.episode = Episode.objects.create(
            series=self.series, name="Pilot", season_number=1, episode_number=1
        )
        self.episode_source = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=self.episode,
            series_relation=self.series_source,
            stream_id="30",
        )
        self.items = [
            {"content_type": "movie", "id": self.movie.pk},
            {"content_type": "series", "id": self.series.pk},
        ]

    def block(self):
        response = self.client.post(
            self.endpoint("bulk"),
            {"items": self.items, "operation": "block"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)

    def test_block_unblock_and_metadata_reset_are_separate(self):
        self.block()
        for content in (self.movie, self.series):
            content.refresh_from_db()
            self.assertTrue(content.library_blocked)
            self.assertFalse(content.tmdb_lookup_excluded)
        response = self.client.post(
            self.endpoint("bulk"),
            {"items": self.items, "operation": "reset"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(Movie.objects.get(pk=self.movie.pk).library_blocked)
        response = self.client.post(
            self.endpoint("bulk"),
            {"items": self.items, "operation": "unblock"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(Movie.objects.get(pk=self.movie.pk).library_blocked)
        self.assertFalse(Series.objects.get(pk=self.series.pk).library_blocked)

    def test_admin_management_sees_blocks_but_clients_cannot_read_them(self):
        self.block()
        response = self.client.get(self.endpoint(), {"blocked": "true"})
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        self.assertTrue(all(row["library_blocked"] for row in response.data["results"]))
        response = self.client.get(
            self.endpoint("details"), {"content_type": "movie", "id": self.movie.pk}
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(self.user)
        for filters in ({}, {"blocked": "true"}, {"blocked": "false"}):
            self.assertEqual(self.client.get(self.endpoint(), filters).data["count"], 0)
        self.assertEqual(
            self.client.get(
                self.endpoint("details"), {"content_type": "movie", "id": self.movie.pk}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(self.endpoint("filter-options")).data["accounts"], []
        )
        self.assertEqual(
            self.client.get(self.endpoint("filter-options")).data["categories"], []
        )
        self.assertEqual(
            self.client.post(
                self.endpoint("bulk"),
                {"items": self.items, "operation": "unblock"},
                format="json",
            ).status_code,
            403,
        )

    @patch("apps.vod.tasks.refresh_series_episodes")
    @patch("apps.vod.tasks.refresh_movie_advanced_data")
    def test_xc_catalogs_and_details_do_not_publish_blocked_titles(
        self, _movie, _series
    ):
        self.block()
        request = RequestFactory().get("/player_api.php")
        self.assertEqual(xc_get_vod_streams(request, self.admin), [])
        self.assertEqual(xc_get_series(request, self.admin), [])
        self.assertEqual(xc_get_vod_categories(self.admin), [])
        self.assertEqual(xc_get_series_categories(self.admin), [])
        for detail, pk in (
            (xc_get_vod_info, self.movie.pk),
            (xc_get_series_info, self.series.pk),
        ):
            with self.assertRaises(Http404):
                detail(request, self.admin, pk)
        _movie.assert_not_called()
        _series.assert_not_called()

    def test_aliases_and_provider_id_fallback_cannot_bypass_a_block(self):
        legacy = Movie.objects.create(name="Old identifier")
        old_id, old_uuid = legacy.pk, legacy.uuid
        remember_alias(legacy, self.movie, "movie")
        legacy.delete()
        self.block()
        self.assertEqual(source_candidates([self.source]), [])
        self.assertEqual(source_candidates([self.episode_source], requirements={}), [])
        for kind, identifier, account, stream in (
            ("movie", old_uuid, None, None),
            ("movie", self.movie.uuid, self.account.pk, self.source.stream_id),
            ("movie", uuid4(), self.account.pk, self.source.stream_id),
            ("episode", self.episode.uuid, None, None),
            ("series", self.series.uuid, None, None),
        ):
            with self.subTest(kind=kind, identifier=identifier):
                self.assertEqual(
                    _get_content_and_relation(kind, identifier, account, stream),
                    (None, None, []),
                )
        for view, kind, identifier in (
            (stream_xc_movie, "movie", old_id),
            (stream_xc_episode, "episode", self.episode.pk),
        ):
            request = APIRequestFactory().get("/synthetic-stream")
            with (
                patch(
                    "apps.proxy.vod_proxy.views.authorize_xc_client",
                    return_value=(self.user, None),
                ),
                patch("apps.proxy.vod_proxy.views.stream_vod") as stream,
            ):
                response = view(
                    request,
                    username="synthetic",
                    password="synthetic",
                    stream_id=identifier,
                    extension="mp4",
                )
                self.assertEqual(response.status_code, 404)
                stream.assert_not_called()

    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_native_get_and_head_fail_before_any_provider_or_session_access(
        self, _network
    ):
        self.block()
        for view, method in ((stream_vod, "get"), (head_vod, "head")):
            for kind, content in (
                ("movie", self.movie),
                ("series", self.series),
                ("episode", self.episode),
            ):
                for session in (None, "existing-session"):
                    with self.subTest(view=view.__name__, kind=kind, session=session):
                        request = getattr(APIRequestFactory(), method)(
                            "/proxy/vod/synthetic"
                        )
                        force_authenticate(request, user=self.user)
                        with (
                            patch(
                                "apps.proxy.vod_proxy.views._select_vod_stream"
                            ) as select,
                            patch(
                                "apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager"
                            ) as manager,
                        ):
                            response = view(
                                request,
                                content_type=kind,
                                content_id=str(content.uuid),
                                session_id=session,
                            )
                            self.assertEqual(response.status_code, 404)
                            select.assert_not_called()
                            manager.assert_not_called()

    def test_refresh_and_identity_merge_preserve_a_global_block(self):
        self.block()
        reconcile_provider_metadata("movie", [self.movie.pk])
        self.movie.refresh_from_db()
        self.assertTrue(self.movie.library_blocked)
        self.movie.tmdb_id = "123"
        self.movie.save()
        target = Movie.objects.create(name="Other canonical")
        result = library.apply_tmdb(target, self.metadata())
        # The chosen unblocked survivor must retain the blocked donor's policy.
        self.assertTrue(result.library_blocked)
