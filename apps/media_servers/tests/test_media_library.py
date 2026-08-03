from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    RedisBackedVODConnection,
    _strip_cross_origin_provider_headers,
)
from apps.proxy.vod_proxy.views import (
    _get_stream_url_from_relation,
    _get_upstream_headers_from_relation,
    _media_library_target_for_request,
)
from apps.vod.models import M3UMovieRelation, Movie
from core.models import CoreSettings
from core.path_browser import browse_directories

from ..models import (
    MediaLibraryExportTarget,
    MediaLibraryImportRun,
    MediaLibraryLocation,
    MediaLibrarySource,
)
from ..local_classification import classify_media_entry
from ..local_metadata import (
    _select_tmdb_candidate,
    enrich_movie_metadata_with_tmdb,
)
from ..path_security import resolve_import_path
from ..serializers import MediaLibrarySourceSerializer
from ..strm_export import build_strm_nfo_snapshot, remove_managed_export_files
from ..tasks import (
    AmbiguousContentMatch,
    ensure_integration_vod_account,
    _find_existing_movie,
    _remove_stale_relations,
    sync_media_server_integration,
)
from ..providers import LocalClient, ProviderLibrary, ProviderMovie


class PathSecurityTests(SimpleTestCase):
    def test_symlinks_must_resolve_below_an_allowed_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            inside = root / "movies"
            inside.mkdir()
            (root / "inside-link").symlink_to(inside, target_is_directory=True)
            (root / "outside-link").symlink_to(outside, target_is_directory=True)

            with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=(str(root),)):
                self.assertEqual(
                    resolve_import_path(
                        str(root / "inside-link"),
                        must_exist=True,
                        require_directory=True,
                    ),
                    inside.resolve(),
                )
                with self.assertRaises(ValidationError):
                    resolve_import_path(
                        str(root / "outside-link"),
                        must_exist=True,
                        require_directory=True,
                    )
                with self.assertRaises(ValidationError):
                    resolve_import_path(str(root / ".." / "outside"))

    def test_shared_directory_browser_has_an_explicit_empty_state(self):
        with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=()):
            result = browse_directories("media-library-import")
        self.assertFalse(result["configured"])
        self.assertEqual(result["roots"], [])
        self.assertIn("MEDIA_LIBRARY_IMPORT_ROOTS", result["configuration_hint"])

    def test_shared_directory_browser_omits_out_of_root_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            outside = Path(temporary) / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "movies").mkdir()
            (root / "inside-link").symlink_to(
                root / "movies",
                target_is_directory=True,
            )
            (root / "outside-link").symlink_to(
                outside,
                target_is_directory=True,
            )
            with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=(str(root),)):
                roots = browse_directories("media-library-import")
                listing = browse_directories("media-library-import", str(root))
                with self.assertRaises(ValidationError):
                    browse_directories(
                        "media-library-import",
                        str(root / ".." / "outside"),
                    )
            self.assertTrue(roots["configured"])
            self.assertTrue(roots["roots"][0]["available"])
            self.assertEqual(listing["root"]["path"], str(root.resolve()))
            self.assertEqual(
                {entry["name"] for entry in listing["entries"]},
                {"inside-link", "movies"},
            )
            self.assertNotIn(
                "outside-link",
                {entry["name"] for entry in listing["entries"]},
            )

    def test_movie_and_multi_episode_filename_classification(self):
        movie = classify_media_entry(
            "movie",
            relative_path="Movies",
            file_name="Example.Movie.2024.1080p.BluRay.mkv",
        )
        self.assertEqual((movie.detected_type, movie.title, movie.year), (
            "movie",
            "Example Movie",
            2024,
        ))

        episode = classify_media_entry(
            "mixed",
            relative_path="Example Show/Season 02",
            file_name="Example.Show.S02E03E04.1080p.mkv",
        )
        self.assertEqual(episode.detected_type, "episode")
        self.assertEqual(episode.season, 2)
        self.assertEqual(episode.episode_list, [3, 4])

    def test_tmdb_title_year_enrichment_rejects_ambiguous_results(self):
        results = [
            {"id": 1, "title": "Example", "release_date": "2024-01-01"},
            {"id": 2, "title": "Example", "release_date": "2024-08-01"},
        ]
        self.assertIsNone(
            _select_tmdb_candidate(results, "Example", year=2024)
        )
        results[1]["release_date"] = "2023-08-01"
        self.assertEqual(
            _select_tmdb_candidate(results, "Example", year=2024)["id"],
            1,
        )

    def test_tmdb_enrichment_respects_the_selected_metadata_priority(self):
        nfo_metadata = {
            "title": "NFO Title",
            "description": "NFO description",
            "year": 2020,
            "poster_url": "/media/poster.jpg",
            "tmdb_id": "123",
        }
        tmdb_details = {
            "id": 123,
            "title": "TMDB Title",
            "overview": "TMDB description",
            "release_date": "2021-01-02",
            "poster_path": "/tmdb-poster.jpg",
            "external_ids": {},
        }
        with (
            patch(
                "apps.media_servers.local_metadata._get_tmdb_api_key",
                return_value="secret",
            ),
            patch(
                "apps.media_servers.local_metadata._tmdb_fetch_details",
                return_value=(tmdb_details, None),
            ),
        ):
            nfo_first, error = enrich_movie_metadata_with_tmdb(
                nfo_metadata,
                title="Filename Title",
                prefer_existing=True,
            )
            tmdb_first, error_2 = enrich_movie_metadata_with_tmdb(
                nfo_metadata,
                title="Filename Title",
                prefer_existing=False,
            )

        self.assertIsNone(error)
        self.assertIsNone(error_2)
        self.assertEqual(nfo_first["title"], "NFO Title")
        self.assertEqual(nfo_first["description"], "NFO description")
        self.assertEqual(nfo_first["poster_url"], "/media/poster.jpg")
        self.assertEqual(tmdb_first["title"], "TMDB Title")
        self.assertEqual(tmdb_first["description"], "TMDB description")
        self.assertEqual(
            tmdb_first["poster_url"],
            "https://image.tmdb.org/t/p/original/tmdb-poster.jpg",
        )

    def test_local_episode_applies_metadata_priority_during_tmdb_enrichment(self):
        with tempfile.TemporaryDirectory() as temporary:
            video_path = Path(temporary) / "Example.Show.S01E01.mp4"
            video_path.touch()
            client = LocalClient.__new__(LocalClient)
            client._location_by_id = {
                "shows": {
                    "id": "shows",
                    "name": "Shows",
                    "path": temporary,
                    "content_type": "series",
                    "include_subdirectories": True,
                }
            }
            client._iter_location_files = lambda *_args, **_kwargs: [
                str(video_path)
            ]

            with (
                patch(
                    "apps.media_servers.providers.prefer_nfo_metadata",
                    return_value=True,
                ),
                patch(
                    "apps.media_servers.providers.find_series_nfo_metadata",
                    return_value=({"title": "Example Show", "tmdb_id": "10"}, None),
                ),
                patch(
                    "apps.media_servers.providers.enrich_series_metadata_with_tmdb",
                    side_effect=lambda metadata, **_kwargs: (metadata, None),
                ),
                patch(
                    "apps.media_servers.providers.find_episode_nfo_metadata",
                    return_value=({"title": "NFO Episode"}, None),
                ) as find_episode_nfo,
                patch(
                    "apps.media_servers.providers.enrich_episode_metadata_with_tmdb",
                    return_value=({"title": "NFO Episode"}, None),
                ) as enrich_episode,
            ):
                series = list(
                    client.iter_series(
                        [
                            ProviderLibrary(
                                id="shows",
                                name="Shows",
                                content_type="series",
                            )
                        ]
                    )
                )

        self.assertEqual(len(series), 1)
        self.assertEqual(len(series[0].episodes), 1)
        find_episode_nfo.assert_called_once_with(
            str(video_path),
            season_number=1,
            episode_number=1,
        )
        self.assertTrue(enrich_episode.call_args.kwargs["prefer_existing"])


class FakeRedis:
    pass


class FakeTaskLock:
    def acquire(self, **kwargs):
        return True

    def extend(self, *args, **kwargs):
        return True

    def release(self):
        return None


class FakeTaskRedis:
    def lock(self, *args, **kwargs):
        return FakeTaskLock()


class RangeAndRedirectTests(SimpleTestCase):
    def test_suffix_and_multiple_ranges(self):
        connection = RedisBackedVODConnection("test", FakeRedis())
        self.assertEqual(
            connection._validate_range_header("bytes=-100", 1000),
            "bytes=900-999",
        )
        self.assertEqual(
            connection._validate_range_header("bytes=100-", 1000),
            "bytes=100-999",
        )
        self.assertIsNone(
            connection._validate_range_header("bytes=0-1,3-4", 1000)
        )
        self.assertIsNone(
            connection._validate_range_header("bytes=1000-", 1000)
        )

    def test_provider_headers_are_removed_on_cross_origin_redirect(self):
        headers = {
            "X-Plex-Token": "secret",
            "X-Emby-Token": "secret",
            "Accept": "*/*",
        }
        self.assertEqual(
            _strip_cross_origin_provider_headers(
                headers,
                "https://plex.local/video",
                "https://cdn.example/video",
            ),
            {"Accept": "*/*"},
        )
        self.assertIn(
            "X-Plex-Token",
            _strip_cross_origin_provider_headers(
                headers,
                "https://plex.local/video",
                "https://plex.local/redirected",
            ),
        )


@override_settings(
    MEDIA_LIBRARY_IMPORT_ROOTS=("/tmp",),
    MEDIA_LIBRARY_EXPORT_ROOTS=("/tmp",),
)
class MediaLibraryDatabaseTests(TestCase):
    def make_account(self, name="Media Library Test"):
        with patch("apps.m3u.signals.refresh_m3u_groups.delay"):
            return M3UAccount.objects.create(
                name=name,
                account_type=M3UAccount.Types.STADNARD,
                is_active=True,
                refresh_interval=0,
            )

    def test_secret_omission_preserves_saved_credentials_and_explicit_clear_works(self):
        source = MediaLibrarySource.objects.create(
            name="Plex",
            provider_type=MediaLibrarySource.ProviderTypes.PLEX,
            base_url="https://plex.example",
            api_token="saved-token",
        )
        serializer = MediaLibrarySourceSerializer(
            source,
            data={"name": "Plex renamed"},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        source.refresh_from_db()
        self.assertEqual(source.api_token, "saved-token")

        serializer = MediaLibrarySourceSerializer(
            source,
            data={"clear_api_token": True, "enabled": False},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        source.refresh_from_db()
        self.assertEqual(source.api_token, "")

    def test_provider_library_media_type_overrides_are_validated_and_saved(self):
        source = MediaLibrarySource.objects.create(
            name="Jellyfin",
            provider_type=MediaLibrarySource.ProviderTypes.JELLYFIN,
            base_url="https://jellyfin.example",
            api_token="saved-token",
        )
        serializer = MediaLibrarySourceSerializer(
            source,
            data={
                "include_libraries": ["movies", "television"],
                "library_content_types": {
                    "movies": "movie",
                    "television": "series",
                },
            },
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()
        source.refresh_from_db()
        self.assertEqual(
            source.configured_library_content_types,
            {"movies": "movie", "television": "series"},
        )
        self.assertEqual(source.content_type_for_library("movies", "mixed"), "movie")
        self.assertEqual(source.content_type_for_library("other", "series"), "series")

        invalid = MediaLibrarySourceSerializer(
            source,
            data={"library_content_types": {"movies": "audio"}},
            partial=True,
        )
        self.assertFalse(invalid.is_valid())
        self.assertIn("library_content_types", invalid.errors)

    def test_managed_vod_account_has_profile_without_generic_m3u_refresh(self):
        source = MediaLibrarySource.objects.create(
            name="Managed local",
            provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
        )
        with patch("apps.m3u.signals.refresh_m3u_groups.delay") as refresh:
            account = ensure_integration_vod_account(source)
        refresh.assert_not_called()
        self.assertTrue(account.locked)
        self.assertIsNone(account.refresh_task_id)
        self.assertTrue(account.profiles.filter(is_default=True).exists())

    def test_local_import_task_creates_playable_relation(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary)
            media_file = root / "Example.Movie.2024.mkv"
            media_file.write_bytes(b"not-real-video")
            media_file.with_suffix(".nfo").write_text(
                """
                <movie>
                  <title>NFO Example Movie</title>
                  <plot>Metadata loaded from the local NFO file.</plot>
                  <year>2019</year>
                  <rating>7.4</rating>
                  <runtime>120</runtime>
                  <genre>Drama</genre>
                  <uniqueid type="tmdb">12345</uniqueid>
                  <uniqueid type="imdb">tt1234567</uniqueid>
                </movie>
                """,
                encoding="utf-8",
            )
            with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=(str(root),)):
                source = MediaLibrarySource.objects.create(
                    name="Local import",
                    provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
                )
                MediaLibraryLocation.objects.create(
                    source=source,
                    name="Movies",
                    path=str(root),
                    content_type=MediaLibraryLocation.ContentTypes.MOVIE,
                )
                run = MediaLibraryImportRun.objects.create(
                    integration=source,
                    status=MediaLibraryImportRun.Status.QUEUED,
                )
                with (
                    patch(
                        "apps.media_servers.tasks.RedisClient.get_client",
                        return_value=FakeTaskRedis(),
                    ),
                    patch(
                        "apps.media_servers.tasks._broadcast_sync_run_update"
                    ),
                    patch(
                        "apps.media_servers.local_metadata._get_tmdb_api_key",
                        return_value=None,
                    ),
                ):
                    result = sync_media_server_integration.run(
                        source.id,
                        run.id,
                    )
                self.assertIn("items processed", result)
                run.refresh_from_db()
                self.assertEqual(
                    run.status,
                    MediaLibraryImportRun.Status.COMPLETED,
                )
                source.refresh_from_db()
                relation = M3UMovieRelation.objects.get(
                    m3u_account=source.vod_account,
                )
                self.assertEqual(
                    relation.custom_properties["file_path"],
                    str(media_file.resolve()),
                )
                self.assertEqual(relation.movie.name, "NFO Example Movie")
                self.assertEqual(relation.movie.year, 2019)
                self.assertEqual(
                    relation.movie.description,
                    "Metadata loaded from the local NFO file.",
                )
                self.assertEqual(relation.movie.tmdb_id, "12345")
                self.assertEqual(relation.movie.imdb_id, "tt1234567")
                self.assertEqual(relation.movie.duration_secs, 7200)

    def test_ambiguous_title_year_match_is_not_merged(self):
        Movie.objects.create(name="Example", year=2024, tmdb_id="1")
        Movie.objects.create(name="Example", year=2024, imdb_id="tt2")
        provider_movie = ProviderMovie(
            external_id="provider-1",
            title="Example",
            category_name="Movies",
            stream_url="https://provider.example/video",
            year=2024,
        )
        with self.assertRaises(AmbiguousContentMatch):
            _find_existing_movie(provider_movie)

    def test_stale_cleanup_is_scope_specific_and_preserves_shared_content(self):
        source_account = self.make_account()
        other_account = self.make_account("Other provider")
        shared_movie = Movie.objects.create(name="Shared", year=2020)
        orphan_movie = Movie.objects.create(name="Orphan", year=2021)
        retained_scope_movie = Movie.objects.create(name="Other scope", year=2022)
        stale_time = timezone.now() - timedelta(hours=1)

        stale_shared = M3UMovieRelation.objects.create(
            m3u_account=source_account,
            movie=shared_movie,
            stream_id="shared-source",
            last_seen=stale_time,
            custom_properties={"provider_library_id": "library-a"},
        )
        M3UMovieRelation.objects.create(
            m3u_account=other_account,
            movie=shared_movie,
            stream_id="shared-other",
            last_seen=stale_time,
        )
        stale_orphan = M3UMovieRelation.objects.create(
            m3u_account=source_account,
            movie=orphan_movie,
            stream_id="orphan-source",
            last_seen=stale_time,
            custom_properties={"provider_library_id": "library-a"},
        )
        retained_relation = M3UMovieRelation.objects.create(
            m3u_account=source_account,
            movie=retained_scope_movie,
            stream_id="scope-b",
            last_seen=stale_time,
            custom_properties={"provider_library_id": "library-b"},
        )

        result = _remove_stale_relations(
            source_account,
            scan_started=timezone.now(),
            authoritative_library_ids={"library-a"},
        )
        self.assertEqual(result["movies"], 2)
        self.assertFalse(M3UMovieRelation.objects.filter(pk=stale_shared.pk).exists())
        self.assertFalse(M3UMovieRelation.objects.filter(pk=stale_orphan.pk).exists())
        self.assertTrue(M3UMovieRelation.objects.filter(pk=retained_relation.pk).exists())
        self.assertTrue(Movie.objects.filter(pk=shared_movie.pk).exists())
        self.assertFalse(Movie.objects.filter(pk=orphan_movie.pk).exists())

    def test_provider_source_is_resolved_server_side_without_token_in_url(self):
        source = MediaLibrarySource.objects.create(
            name="Jellyfin",
            provider_type=MediaLibrarySource.ProviderTypes.JELLYFIN,
            base_url="https://jellyfin.example",
            api_token="server-secret",
        )
        account = self.make_account()
        movie = Movie.objects.create(name="Remote", year=2023)
        relation = M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="remote",
            custom_properties={
                "managed_source": "media_server",
                "integration_id": source.id,
                "source_url": "https://jellyfin.example/Videos/1/stream?Static=true",
            },
        )
        self.assertNotIn("server-secret", _get_stream_url_from_relation(relation))
        self.assertEqual(
            _get_upstream_headers_from_relation(relation),
            {"X-Emby-Token": "server-secret"},
        )

    def test_export_writes_scoped_urls_and_only_removes_manifest_owned_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            account = self.make_account()
            movie = Movie.objects.create(
                name="Exported",
                year=2024,
                tmdb_id="42",
            )
            relation = M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id="stream",
            )
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Jellyfin",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                    playback_cidrs="192.0.2.0/24",
                )
                summary = build_strm_nfo_snapshot(target)
                strm = next(root.rglob("*.strm"))
                contents = strm.read_text()
                self.assertIn(
                    f"/proxy/vod/media-library/{target.public_id}/movie/{movie.uuid}",
                    contents,
                )
                self.assertNotIn("token", contents.lower())
                self.assertEqual(summary["strm_files_written"], 1)
                nfo = next(root.rglob("*.nfo")).read_text()
                self.assertIn("<tmdbid>42</tmdbid>", nfo)
                self.assertNotIn("dispatcharr_metadata", nfo)

                untracked = root / "keep-me.txt"
                untracked.write_text("owned by operator")
                relation.delete()
                build_strm_nfo_snapshot(target)
                self.assertTrue(untracked.exists())
                self.assertFalse(strm.exists())
                manifest = json.loads(
                    (root / ".dispatcharr-media-library.json").read_text()
                )
                self.assertEqual(manifest["state"], "complete")
                self.assertEqual(manifest["files"], [])

    def test_target_cidr_is_mandatory_and_enforced(self):
        target = MediaLibraryExportTarget.objects.create(
            name="Emby",
            output_root="/tmp/export-target-cidr",
            playback_base_url="https://dispatcharr.example",
            playback_cidrs="192.0.2.0/24",
        )
        factory = RequestFactory()
        allowed = factory.get("/", REMOTE_ADDR="192.0.2.10")
        denied = factory.get("/", REMOTE_ADDR="198.51.100.10")
        self.assertEqual(
            _media_library_target_for_request(allowed, target.public_id).pk,
            target.pk,
        )
        self.assertIs(
            _media_library_target_for_request(denied, target.public_id),
            False,
        )

    def test_scoped_playback_url_is_credential_free_but_network_restricted(self):
        target = MediaLibraryExportTarget.objects.create(
            name="Playback route",
            output_root="/tmp/export-target-route",
            playback_base_url="https://dispatcharr.example",
            playback_cidrs="127.0.0.1/32",
        )
        path = (
            f"/proxy/vod/media-library/{target.public_id}/movie/{uuid.uuid4()}"
        )
        client = APIClient()
        with patch(
            "apps.proxy.vod_proxy.views.network_access_allowed",
            return_value=True,
        ):
            response = client.get(path, REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 301)
            self.assertIn(str(target.public_id), response["Location"])
            self.assertNotIn("token", response["Location"].lower())

            response = client.get(path, REMOTE_ADDR="198.51.100.10")
            self.assertEqual(response.status_code, 403)

    def test_management_api_is_admin_only(self):
        normal = User.objects.create_user(
            username="normal",
            password="test",
            user_level=User.UserLevel.STANDARD,
        )
        admin = User.objects.create_user(
            username="admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(normal)
        self.assertEqual(client.get("/api/media-library/sources/").status_code, 403)
        self.assertEqual(
            client.get(
                "/api/core/directories/browse/",
                {"scope": "media-library-import"},
            ).status_code,
            403,
        )
        client.force_authenticate(admin)
        self.assertEqual(client.get("/api/media-library/sources/").status_code, 200)
        browser_response = client.get(
            "/api/core/directories/browse/",
            {"scope": "media-library-import"},
        )
        self.assertEqual(browser_response.status_code, 200)
        self.assertTrue(browser_response.json()["configured"])

    def test_tmdb_settings_are_write_only_and_require_explicit_clear(self):
        admin = User.objects.create_user(
            username="settings-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(admin)

        with patch.dict(os.environ, {"TMDB_API_KEY": ""}):
            response = client.patch(
                "/api/media-library/settings/",
                {"tmdb_api_key": "tmdb-secret", "prefer_nfo": False},
                format="json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["tmdb_configured"])
            self.assertTrue(response.json()["tmdb_saved"])
            self.assertFalse(response.json()["prefer_nfo"])
            self.assertNotContains(response, "tmdb-secret")
            self.assertEqual(
                CoreSettings._get_group("media_library_settings", {})[
                    "tmdb_api_key"
                ],
                "tmdb-secret",
            )
            self.assertFalse(
                CoreSettings._get_group("media_library_settings", {})[
                    "prefer_nfo"
                ]
            )

            invalid_priority = client.patch(
                "/api/media-library/settings/",
                {"prefer_nfo": "false"},
                format="json",
            )
            self.assertEqual(invalid_priority.status_code, 400)

            blank = client.patch(
                "/api/media-library/settings/",
                {"tmdb_api_key": ""},
                format="json",
            )
            self.assertEqual(blank.status_code, 400)
            self.assertEqual(
                CoreSettings._get_group("media_library_settings", {})[
                    "tmdb_api_key"
                ],
                "tmdb-secret",
            )

            cleared = client.patch(
                "/api/media-library/settings/",
                {"clear_tmdb_api_key": True},
                format="json",
            )
            self.assertEqual(cleared.status_code, 200)
            self.assertFalse(cleared.json()["tmdb_configured"])

    def test_unsaved_local_configuration_can_be_tested_safely(self):
        admin = User.objects.create_user(
            username="configuration-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(admin)
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary)
            (root / "Example.Movie.2024.mp4").write_bytes(b"test")
            with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=(str(root),)):
                response = client.post(
                    "/api/media-library/sources/test-configuration/",
                    {
                        "name": "Unsaved local source",
                        "provider_type": "local",
                        "locations": [
                            {
                                "name": "Movies",
                                "path": str(root),
                                "content_type": "movie",
                                "include_subdirectories": True,
                                "enabled": True,
                            }
                        ],
                    },
                    format="json",
                )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["library_count"], 1)
        self.assertFalse(
            MediaLibrarySource.objects.filter(name="Unsaved local source").exists()
        )

    def test_run_history_can_be_filtered_purged_and_queued_runs_removed(self):
        admin = User.objects.create_user(
            username="history-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        source = MediaLibrarySource.objects.create(
            name="History source",
            provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
        )
        other = MediaLibrarySource.objects.create(
            name="Other history source",
            provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
        )
        completed = MediaLibraryImportRun.objects.create(
            integration=source,
            status=MediaLibraryImportRun.Status.COMPLETED,
        )
        queued = MediaLibraryImportRun.objects.create(
            integration=other,
            status=MediaLibraryImportRun.Status.QUEUED,
        )
        client = APIClient()
        client.force_authenticate(admin)

        filtered = client.get(
            "/api/media-library/import-runs/",
            {"source": source.id},
        )
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual([entry["id"] for entry in filtered.json()], [completed.id])

        purged = client.delete(
            f"/api/media-library/import-runs/purge/?source={source.id}"
        )
        self.assertEqual(purged.status_code, 200)
        self.assertFalse(
            MediaLibraryImportRun.objects.filter(pk=completed.pk).exists()
        )
        self.assertTrue(MediaLibraryImportRun.objects.filter(pk=queued.pk).exists())

        removed = client.delete(f"/api/media-library/import-runs/{queued.id}/")
        self.assertEqual(removed.status_code, 204)

    def test_managed_export_cleanup_preserves_untracked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            account = self.make_account("Cleanup account")
            movie = Movie.objects.create(name="Cleanup movie", year=2024)
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id="cleanup-stream",
            )
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Cleanup target",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                    playback_cidrs="192.0.2.0/24",
                )
                build_strm_nfo_snapshot(target)
                untracked = root / "operator-file.txt"
                untracked.write_text("preserve me")
                result = remove_managed_export_files(target)
                self.assertGreater(result["managed_files_deleted"], 0)
                self.assertTrue(untracked.exists())
