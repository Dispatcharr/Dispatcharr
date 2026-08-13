from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.proxy.vod_proxy.multi_worker_connection_manager import (
    MultiWorkerVODConnectionManager,
    RedisBackedVODConnection,
    _strip_cross_origin_provider_headers,
)
from apps.proxy.vod_proxy.views import (
    _get_content_and_relation,
    _get_stream_url_from_relation,
    _get_upstream_headers_from_relation,
    _media_library_target_for_request,
)
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODCategory,
    VODLogo,
)
from core.models import CoreSettings
from core.path_browser import browse_directories, create_directory

from ..models import (
    MediaLibraryExportRun,
    MediaLibraryExportTarget,
    MediaLibraryImportRun,
    MediaLibraryLocation,
    MediaLibrarySource,
)
from ..artwork import delete_media_library_logo_if_unused
from ..export_policy import (
    export_relation_groups,
    safe_export_relations,
)
from ..local_classification import classify_media_entry
from ..local_metadata import (
    _select_tmdb_candidate,
    enrich_movie_metadata_with_tmdb,
    find_episode_nfo_metadata,
    find_movie_nfo_metadata,
    parse_nfo_episode_entries,
)
from ..path_security import resolve_import_path
from ..serializers import MediaLibrarySourceSerializer
from ..strm_export import build_strm_nfo_snapshot, remove_managed_export_files
from ..tasks import (
    AmbiguousContentMatch,
    _sync_movie,
    ensure_integration_vod_account,
    _find_existing_movie,
    _cache_artwork,
    _remove_stale_relations,
    remove_dvr_media_library_recording,
    sync_media_server_integration,
    sync_dvr_media_library_after_recording,
)
from ..providers import DVRClient, LocalClient, ProviderLibrary, ProviderMovie
from ..dvr_library import ensure_dvr_media_library_source
from ..export_tasks import refresh_selected_series_and_export
from ..signals import _vod_task_result_succeeded, queue_export_after_vod_task
from apps.vod.tasks import handle_movie_id_conflicts, handle_series_id_conflicts


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

    def test_shared_directory_browser_creates_folder_in_current_export_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "exports"
            current = root / "jellyfin"
            current.mkdir(parents=True)
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                listing = browse_directories(
                    "media-library-export",
                    str(current),
                )
                created = create_directory(
                    "media-library-export",
                    str(current),
                    "STRM Library",
                )

            self.assertTrue(listing["allows_create"])
            self.assertTrue(listing["can_create"])
            self.assertEqual(
                Path(created["path"]),
                (current / "STRM Library").resolve(),
            )
            self.assertTrue((current / "STRM Library").is_dir())

    def test_shared_directory_browser_rejects_creation_for_import_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=(str(root),)):
                with self.assertRaises(ValidationError):
                    create_directory(
                        "media-library-import",
                        str(root),
                        "not-allowed",
                    )

    def test_shared_directory_browser_rejects_path_in_folder_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                for name in ("../outside", "nested/folder", "nested\\folder"):
                    with self.subTest(name=name), self.assertRaises(ValidationError):
                        create_directory(
                            "media-library-export",
                            str(root),
                            name,
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
        self.assertTrue(series[0].replace_metadata)
        self.assertTrue(series[0].episodes[0].replace_metadata)
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
    def make_account(
        self,
        name="Media Library Test",
        *,
        account_type=M3UAccount.Types.STADNARD,
    ):
        with patch("apps.m3u.signals.refresh_m3u_groups.delay"):
            return M3UAccount.objects.create(
                name=name,
                account_type=account_type,
                is_active=True,
                refresh_interval=0,
            )

    def test_authoritative_local_metadata_refreshes_existing_movie_fields(self):
        source = MediaLibrarySource.objects.create(
            name="Local metadata refresh",
            provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
        )
        movie = Movie.objects.create(
            name="Filename Title",
            description="Old description",
            year=2001,
            rating="1.0",
            genre="Old genre",
            duration_secs=60,
        )
        provider_movie = ProviderMovie(
            external_id="stable-local-path",
            title="NFO Title",
            category_name="Movies",
            stream_url="",
            year=2024,
            description="Updated from NFO",
            rating="8.5",
            duration_secs=7200,
            genres=["Drama", "Mystery"],
            replace_metadata=True,
        )

        refreshed, created, updated = _sync_movie(
            source,
            provider_movie,
            existing=movie,
        )

        self.assertFalse(created)
        self.assertTrue(updated)
        self.assertEqual(refreshed.name, "NFO Title")
        self.assertEqual(refreshed.description, "Updated from NFO")
        self.assertEqual(refreshed.year, 2024)
        self.assertEqual(refreshed.rating, "8.5")
        self.assertEqual(refreshed.genre, "Drama, Mystery")
        self.assertEqual(refreshed.duration_secs, 7200)

    def test_filename_only_rescan_does_not_replace_existing_movie_metadata(self):
        source = MediaLibrarySource.objects.create(
            name="Local filename-only refresh",
            provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
        )
        movie = Movie.objects.create(
            name="Curated Title",
            description="Curated description",
            year=2020,
        )
        provider_movie = ProviderMovie(
            external_id="stable-local-path",
            title="Filename Guess",
            category_name="Movies",
            stream_url="",
            year=2021,
            replace_metadata=False,
        )

        refreshed, created, updated = _sync_movie(
            source,
            provider_movie,
            existing=movie,
        )

        self.assertFalse(created)
        self.assertFalse(updated)
        self.assertEqual(refreshed.name, "Curated Title")
        self.assertEqual(refreshed.description, "Curated description")
        self.assertEqual(refreshed.year, 2020)

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
        self.assertEqual(account.priority, 10000)
        self.assertIsNone(account.refresh_task_id)
        self.assertTrue(account.profiles.filter(is_default=True).exists())

        source.vod_priority = 25000
        source.save(update_fields=["vod_priority", "updated_at"])
        updated_account = ensure_integration_vod_account(source)
        self.assertEqual(updated_account.id, account.id)
        self.assertEqual(updated_account.priority, 25000)

    def test_import_priority_drives_normal_vod_provider_selection(self):
        source = MediaLibrarySource.objects.create(
            name="Preferred local source",
            provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
        )
        with patch("apps.m3u.signals.refresh_m3u_groups.delay"):
            imported_account = ensure_integration_vod_account(source)
            remote_account = self.make_account("Lower priority XC")
        remote_account.priority = 9999
        remote_account.save(update_fields=["priority"])

        movie = Movie.objects.create(name="Priority Movie", year=2024)
        imported_relation = M3UMovieRelation.objects.create(
            m3u_account=imported_account,
            movie=movie,
            stream_id="local-priority",
        )
        remote_relation = M3UMovieRelation.objects.create(
            m3u_account=remote_account,
            movie=movie,
            stream_id="remote-priority",
        )

        _, selected, candidates = _get_content_and_relation(
            "movie",
            movie.uuid,
        )
        self.assertEqual(selected.id, imported_relation.id)
        self.assertEqual(
            [relation.id for relation in candidates],
            [imported_relation.id, remote_relation.id],
        )

        source.vod_priority = 5000
        source.save(update_fields=["vod_priority", "updated_at"])
        ensure_integration_vod_account(source)
        _, selected_after_change, candidates_after_change = (
            _get_content_and_relation("movie", movie.uuid)
        )
        self.assertEqual(selected_after_change.id, remote_relation.id)
        self.assertEqual(
            [relation.id for relation in candidates_after_change],
            [remote_relation.id, imported_relation.id],
        )

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
            account = self.make_account(account_type=M3UAccount.Types.XC)
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
            unselected_movie = Movie.objects.create(name="Not exported", year=2023)
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=unselected_movie,
                stream_id="unselected-stream",
            )
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Jellyfin",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_movies.add(movie)
                summary = build_strm_nfo_snapshot(target)
                strm = next(root.rglob("*.strm"))
                contents = strm.read_text()
                self.assertIn(
                    f"/proxy/vod/media-library/{target.public_id}/movie/{movie.uuid}",
                    contents,
                )
                self.assertNotIn("token", contents.lower())
                self.assertEqual(summary["strm_files_written"], 1)
                self.assertNotIn("Not exported", str(list(root.rglob("*.strm"))))
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

    def test_export_omits_movie_already_present_in_remote_media_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xc_account = self.make_account(
                "XC origin",
                account_type=M3UAccount.Types.XC,
            )
            emby_account = self.make_account("Emby inventory")
            emby_account.custom_properties = {
                "managed_source": "media_server",
                "provider": "emby",
            }
            emby_account.save(update_fields=["custom_properties"])
            movie = Movie.objects.create(name="Avatar", year=2009)
            M3UMovieRelation.objects.create(
                m3u_account=xc_account,
                movie=movie,
                stream_id="xc-avatar",
            )

            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Existing movie policy",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_movies.add(movie)
                first = build_strm_nfo_snapshot(target)
                self.assertEqual(first["movies_written"], 1)
                self.assertTrue(next(root.rglob("*.strm")).is_file())

                M3UMovieRelation.objects.create(
                    m3u_account=emby_account,
                    movie=movie,
                    stream_id="emby-avatar",
                    custom_properties={
                        "managed_source": "media_server",
                        "provider": "emby",
                    },
                )
                emby_account.is_active = False
                emby_account.save(update_fields=["is_active"])
                second = build_strm_nfo_snapshot(target)

            self.assertEqual(second["movies_written"], 0)
            self.assertEqual(second["movies_skipped_existing"], 1)
            self.assertEqual(list(root.rglob("*.strm")), [])
            self.assertEqual(list(root.rglob("*.nfo")), [])
            self.assertGreaterEqual(second["stale_files_removed"], 1)

    def test_local_import_is_a_safe_export_source(self):
        local_account = self.make_account("Local origin")
        local_account.custom_properties = {
            "managed_source": "media_server",
            "provider": "local",
        }
        local_account.save(update_fields=["custom_properties"])
        movie = Movie.objects.create(name="Local movie", year=2024)
        relation = M3UMovieRelation.objects.create(
            m3u_account=local_account,
            movie=movie,
            stream_id="local-movie",
            custom_properties={
                "managed_source": "media_server",
                "provider": "local",
            },
        )
        safe, remote = export_relation_groups([relation])
        self.assertEqual(safe, [relation])
        self.assertEqual(remote, [])
        self.assertEqual(safe_export_relations([relation]), [relation])

    def test_dvr_import_is_a_safe_export_source(self):
        dvr_account = self.make_account("DVR origin")
        dvr_account.custom_properties = {
            "managed_source": "media_server",
            "provider": "dvr",
        }
        dvr_account.save(update_fields=["custom_properties"])
        movie = Movie.objects.create(name="Recorded movie", year=2026)
        relation = M3UMovieRelation.objects.create(
            m3u_account=dvr_account,
            movie=movie,
            stream_id="dvr-movie",
            custom_properties={
                "managed_source": "media_server",
                "provider": "dvr",
            },
        )
        safe, remote = export_relation_groups([relation])
        self.assertEqual(safe, [relation])
        self.assertEqual(remote, [])
        self.assertEqual(safe_export_relations([relation]), [relation])

    def test_export_includes_only_tv_episodes_with_active_playback_relations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            account = self.make_account(account_type=M3UAccount.Types.XC)
            series = Series.objects.create(name="Exported Show", year=2024)
            episode = Episode.objects.create(
                series=series,
                name="Pilot",
                season_number=1,
                episode_number=1,
            )
            series_relation = M3USeriesRelation.objects.create(
                m3u_account=account,
                series=series,
                external_series_id="show-1",
            )
            M3UEpisodeRelation.objects.create(
                m3u_account=account,
                episode=episode,
                series_relation=series_relation,
                stream_id="episode-1",
            )

            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="TV export",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_series.add(series)
                summary = build_strm_nfo_snapshot(target)
                self.assertEqual(summary["series_written"], 1)
                self.assertEqual(summary["episodes_written"], 1)
                self.assertTrue(next((root / "TV Shows").rglob("*.strm")).is_file())

                account.is_active = False
                account.save(update_fields=["is_active"])
                summary = build_strm_nfo_snapshot(target)
                self.assertEqual(summary["series_written"], 0)
                self.assertEqual(summary["episodes_written"], 0)
                self.assertEqual(list((root / "TV Shows").rglob("*.strm")), [])
                self.assertEqual(list((root / "TV Shows").rglob("*.nfo")), [])

    def test_export_omits_episode_already_present_in_remote_media_server(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xc_account = self.make_account(
                "XC episode origin",
                account_type=M3UAccount.Types.XC,
            )
            jellyfin_account = self.make_account("Jellyfin inventory")
            jellyfin_account.custom_properties = {
                "managed_source": "media_server",
                "provider": "jellyfin",
            }
            jellyfin_account.save(update_fields=["custom_properties"])
            series = Series.objects.create(name="Existing Show", year=2024)
            episode = Episode.objects.create(
                series=series,
                name="Pilot",
                season_number=1,
                episode_number=1,
            )
            xc_series = M3USeriesRelation.objects.create(
                m3u_account=xc_account,
                series=series,
                external_series_id="xc-show",
            )
            jellyfin_series = M3USeriesRelation.objects.create(
                m3u_account=jellyfin_account,
                series=series,
                external_series_id="jellyfin-show",
                custom_properties={
                    "managed_source": "media_server",
                    "provider": "jellyfin",
                },
            )
            M3UEpisodeRelation.objects.create(
                m3u_account=xc_account,
                episode=episode,
                series_relation=xc_series,
                stream_id="xc-episode",
            )
            M3UEpisodeRelation.objects.create(
                m3u_account=jellyfin_account,
                episode=episode,
                series_relation=jellyfin_series,
                stream_id="jellyfin-episode",
                custom_properties={
                    "managed_source": "media_server",
                    "provider": "jellyfin",
                },
            )

            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Existing episode policy",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_series.add(series)
                summary = build_strm_nfo_snapshot(target)

            self.assertEqual(summary["series_written"], 0)
            self.assertEqual(summary["episodes_written"], 0)
            self.assertEqual(summary["episodes_skipped_existing"], 1)
            self.assertEqual(list(root.rglob("*.strm")), [])

    def test_export_selection_api_supports_filters_and_blocks_series_select_all(self):
        admin = User.objects.create_user(
            username="selection-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        account = self.make_account("Selection provider")
        movie_category = VODCategory.objects.create(
            name="Action",
            category_type="movie",
        )
        series_category = VODCategory.objects.create(
            name="Drama",
            category_type="series",
        )
        movie = Movie.objects.create(name="Selected Movie", year=2024)
        other_movie = Movie.objects.create(name="Other Movie", year=2023)
        series = Series.objects.create(name="Selected Series", year=2022)
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            category=movie_category,
            stream_id="selected-movie",
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=other_movie,
            stream_id="other-movie",
        )
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            category=series_category,
            external_series_id="selected-series",
        )
        target = MediaLibraryExportTarget.objects.create(
            name="Selection target",
            output_root="/tmp/export-selection-target",
            playback_base_url="https://dispatcharr.example",
        )
        client = APIClient()
        client.force_authenticate(admin)
        base = f"/api/media-library/export-targets/{target.id}"

        options = client.get(f"{base}/selection-options/")
        self.assertEqual(options.status_code, 200, options.content)
        self.assertIn(
            {"value": str(account.id), "label": account.name},
            options.json()["providers"],
        )
        self.assertIn(
            {"value": str(movie_category.id), "label": movie_category.name},
            options.json()["movie_categories"],
        )
        self.assertIn(
            {"value": str(series_category.id), "label": series_category.name},
            options.json()["series_categories"],
        )

        catalog = client.get(
            f"{base}/selection-catalog/",
            {"content_type": "movie", "category": movie_category.id},
        )
        self.assertEqual(catalog.status_code, 200, catalog.content)
        self.assertEqual([entry["id"] for entry in catalog.json()["results"]], [movie.id])

        selected = client.post(
            f"{base}/selection/",
            {
                "content_type": "movie",
                "operation": "select",
                "matching": True,
                "provider": account.id,
            },
            format="json",
        )
        self.assertEqual(selected.status_code, 200, selected.content)
        self.assertEqual(selected.json()["selected_count"], 2)

        blocked = client.post(
            f"{base}/selection/",
            {
                "content_type": "series",
                "operation": "select",
                "matching": True,
            },
            format="json",
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertFalse(target.selected_series.exists())

        selected_series = client.post(
            f"{base}/selection/",
            {
                "content_type": "series",
                "operation": "select",
                "ids": [series.id],
            },
            format="json",
        )
        self.assertEqual(selected_series.status_code, 200, selected_series.content)
        target.refresh_from_db()
        self.assertEqual(target.selected_series.get(), series)

        details = client.get(f"/api/media-library/export-targets/{target.id}/")
        self.assertEqual(details.json()["selected_movie_count"], 2)
        self.assertEqual(details.json()["selected_series_count"], 1)

    def test_selected_series_schedule_tracks_interval_and_selection(self):
        account = self.make_account("Scheduled provider")
        series = Series.objects.create(name="Scheduled Series", year=2024)
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="scheduled-series",
        )
        target = MediaLibraryExportTarget.objects.create(
            name="Scheduled target",
            output_root="/tmp/export-scheduled-target",
            playback_base_url="https://dispatcharr.example",
            series_refresh_interval=6,
        )
        target.refresh_from_db()
        self.assertFalse(target.series_refresh_task.enabled)

        target.selected_series.add(series)
        target.refresh_from_db()
        self.assertTrue(target.series_refresh_task.enabled)
        self.assertEqual(target.series_refresh_task.interval.every, 6)
        self.assertEqual(
            target.series_refresh_task.task,
            "apps.media_servers.export_tasks.refresh_selected_series_and_export",
        )

        target.selected_series.clear()
        target.refresh_from_db()
        self.assertFalse(target.series_refresh_task.enabled)

    def test_manual_export_refreshes_selected_series_before_building(self):
        admin = User.objects.create_user(
            username="export-refresh-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        target = MediaLibraryExportTarget.objects.create(
            name="Manual refresh target",
            output_root="/tmp/export-manual-refresh-target",
            playback_base_url="https://dispatcharr.example",
        )
        client = APIClient()
        client.force_authenticate(admin)
        with patch(
            "apps.media_servers.api_views.refresh_selected_series_and_export.delay"
        ) as queued:
            queued.return_value.id = "refresh-task-id"
            response = client.post(
                f"/api/media-library/export-targets/{target.id}/export/"
            )
        self.assertEqual(response.status_code, 202, response.content)
        run = MediaLibraryExportRun.objects.get(target=target)
        queued.assert_called_once_with(target.id, run.id, "manual")
        self.assertEqual(run.task_id, "refresh-task-id")

    def test_selected_series_refresh_uses_current_selection_then_queues_export(self):
        account = self.make_account("Selected-series XC provider")
        M3UAccount.objects.filter(pk=account.pk).update(
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example",
            username="user",
            password="password",
        )
        account.refresh_from_db()
        selected = Series.objects.create(name="Needs Episodes", year=2024)
        unselected = Series.objects.create(name="Not Selected", year=2023)
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=selected,
            external_series_id="selected",
        )
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=unselected,
            external_series_id="unselected",
        )
        target = MediaLibraryExportTarget.objects.create(
            name="Refresh orchestration target",
            output_root="/tmp/export-refresh-orchestration-target",
            playback_base_url="https://dispatcharr.example",
        )
        target.selected_series.add(selected)
        run = MediaLibraryExportRun.objects.create(
            target=target,
            status=MediaLibraryExportRun.Status.QUEUED,
            reason="manual",
        )

        lock = patch("apps.media_servers.export_tasks.RedisClient.get_client")
        with lock as redis_client, patch(
            "apps.vod.tasks.refresh_due_series_episodes",
            return_value={"total": 1, "refreshed": 1, "failed": 0},
        ) as refresh, patch(
            "apps.media_servers.export_tasks.export_media_library.delay"
        ) as export:
            redis_lock = redis_client.return_value.lock.return_value
            redis_lock.acquire.return_value = True
            export.return_value.id = "export-task-id"
            result = refresh_selected_series_and_export.run(
                target.id,
                run.id,
                "manual",
            )

        refresh.assert_called_once_with(
            account,
            series_ids=[selected.id],
            progress_callback=ANY,
        )
        export.assert_called_once_with(target.id, run.id)
        run.refresh_from_db()
        self.assertEqual(run.status, MediaLibraryExportRun.Status.QUEUED)
        self.assertEqual(run.task_id, "export-task-id")
        self.assertEqual(result["accounts"][str(account.id)]["refreshed"], 1)

    def test_selected_series_refresh_failure_does_not_rebuild_export(self):
        account = self.make_account(
            "Failing selected-series provider",
            account_type=M3UAccount.Types.XC,
        )
        series = Series.objects.create(name="Unavailable Episodes", year=2024)
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="failed-series",
        )
        target = MediaLibraryExportTarget.objects.create(
            name="Failed refresh target",
            output_root="/tmp/export-failed-refresh-target",
            playback_base_url="https://dispatcharr.example",
        )
        target.selected_series.add(series)
        run = MediaLibraryExportRun.objects.create(
            target=target,
            status=MediaLibraryExportRun.Status.QUEUED,
            reason="manual",
        )

        with patch(
            "apps.media_servers.export_tasks.RedisClient.get_client"
        ) as redis_client, patch(
            "apps.vod.tasks.refresh_due_series_episodes",
            return_value={
                "total": 1,
                "refreshed": 0,
                "failed": 1,
                "failed_series": [
                    {
                        "id": series.id,
                        "name": series.name,
                        "external_series_id": "failed-series",
                    }
                ],
            },
        ), patch(
            "apps.media_servers.export_tasks.export_media_library.delay"
        ) as export:
            redis_lock = redis_client.return_value.lock.return_value
            redis_lock.acquire.return_value = True
            with self.assertRaisesRegex(RuntimeError, "failed to refresh"):
                refresh_selected_series_and_export.run(
                    target.id,
                    run.id,
                    "manual",
                )

        export.assert_not_called()
        run.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(run.status, MediaLibraryExportRun.Status.FAILED)
        self.assertEqual(
            run.summary["series_refresh"]["accounts"][str(account.id)]["failed"],
            1,
        )
        self.assertEqual(
            target.last_export_status,
            MediaLibraryExportTarget.ExportStatus.ERROR,
        )

    def test_target_identifier_resolves_independently_of_client_network(self):
        target = MediaLibraryExportTarget.objects.create(
            name="Emby",
            output_root="/tmp/export-target-cidr",
            playback_base_url="https://dispatcharr.example",
        )
        factory = RequestFactory()
        for address in ("192.0.2.10", "198.51.100.10"):
            request = factory.get("/", REMOTE_ADDR=address)
            self.assertEqual(
                _media_library_target_for_request(request, target.public_id).pk,
                target.pk,
            )

    def test_scoped_playback_uses_global_stream_network_policy(self):
        target = MediaLibraryExportTarget.objects.create(
            name="Playback route",
            output_root="/tmp/export-target-route",
            playback_base_url="https://dispatcharr.example",
        )
        path = (
            f"/proxy/vod/media-library/{target.public_id}/movie/{uuid.uuid4()}"
        )
        client = APIClient()
        with patch(
            "apps.proxy.vod_proxy.views.network_access_allowed",
            side_effect=(True, False),
        ) as network_allowed:
            response = client.get(path, REMOTE_ADDR="127.0.0.1")
            self.assertEqual(response.status_code, 301)
            self.assertIn(str(target.public_id), response["Location"])
            self.assertNotIn("token", response["Location"].lower())

            response = client.get(path, REMOTE_ADDR="198.51.100.10")
            self.assertEqual(response.status_code, 403)
        self.assertEqual(network_allowed.call_count, 2)
        self.assertTrue(
            all(call.args[1] == "STREAMS" for call in network_allowed.call_args_list)
        )

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
        self.assertEqual(
            client.post(
                "/api/core/directories/create/",
                {
                    "scope": "media-library-export",
                    "path": "/tmp",
                    "name": "denied",
                },
                format="json",
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
        with tempfile.TemporaryDirectory() as temporary:
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(temporary,)):
                create_response = client.post(
                    "/api/core/directories/create/",
                    {
                        "scope": "media-library-export",
                        "path": temporary,
                        "name": "Jellyfin",
                    },
                    format="json",
                )
            self.assertEqual(create_response.status_code, 201)
            self.assertEqual(
                Path(create_response.json()["path"]),
                (Path(temporary) / "Jellyfin").resolve(),
            )

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
            account = self.make_account(
                "Cleanup account",
                account_type=M3UAccount.Types.XC,
            )
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
                )
                target.selected_movies.add(movie)
                build_strm_nfo_snapshot(target)
                untracked = root / "operator-file.txt"
                untracked.write_text("preserve me")
                result = remove_managed_export_files(target)
                self.assertGreater(result["managed_files_deleted"], 0)
                self.assertTrue(untracked.exists())

    def test_deleting_export_target_removes_only_managed_files(self):
        admin = User.objects.create_user(
            username="export-cleanup-admin",
            password="secret",
            user_level=User.UserLevel.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(admin)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            account = self.make_account(
                "Delete cleanup account",
                account_type=M3UAccount.Types.XC,
            )
            movie = Movie.objects.create(name="Delete cleanup movie", year=2024)
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id="delete-cleanup-stream",
            )
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Delete cleanup target",
                    output_root=str(root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_movies.add(movie)
                build_strm_nfo_snapshot(target)
                unmanaged = root / "keep.txt"
                unmanaged.write_text("operator-owned", encoding="utf-8")

                with self.captureOnCommitCallbacks(execute=True):
                    response = client.delete(
                        f"/api/media-library/export-targets/{target.id}/"
                    )

            self.assertEqual(response.status_code, 204, response.content)
            self.assertTrue(unmanaged.exists())
            self.assertFalse((root / ".dispatcharr-media-library.json").exists())
            self.assertFalse(any((root / "Movies").rglob("*.strm")))

    def test_changing_export_root_cleans_old_snapshot_and_queues_rebuild(self):
        admin = User.objects.create_user(
            username="export-move-admin",
            password="secret",
            user_level=User.UserLevel.ADMIN,
        )
        client = APIClient()
        client.force_authenticate(admin)
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            old_root = parent / "old"
            new_root = parent / "new"
            old_root.mkdir()
            new_root.mkdir()
            account = self.make_account(
                "Move cleanup account",
                account_type=M3UAccount.Types.XC,
            )
            movie = Movie.objects.create(name="Move cleanup movie", year=2024)
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id="move-cleanup-stream",
            )
            with override_settings(MEDIA_LIBRARY_EXPORT_ROOTS=(str(parent),)):
                target = MediaLibraryExportTarget.objects.create(
                    name="Move cleanup target",
                    output_root=str(old_root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_movies.add(movie)
                build_strm_nfo_snapshot(target)
                unmanaged = old_root / "keep.txt"
                unmanaged.write_text("operator-owned", encoding="utf-8")

                with patch(
                    "apps.media_servers.api_views."
                    "MediaLibraryExportTargetViewSet._queue_export"
                ) as queue_export, self.captureOnCommitCallbacks(execute=True):
                    response = client.patch(
                        f"/api/media-library/export-targets/{target.id}/",
                        {"output_root": str(new_root)},
                        format="json",
                    )

            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(unmanaged.exists())
            self.assertFalse((old_root / ".dispatcharr-media-library.json").exists())
            self.assertFalse(any((old_root / "Movies").rglob("*.strm")))
            target.refresh_from_db()
            queue_export.assert_called_once_with(
                target,
                "target-configuration-changed",
            )

    def test_unused_media_library_artwork_file_is_removed_with_logo(self):
        with tempfile.TemporaryDirectory() as temporary:
            artwork = Path(temporary) / "unused.jpg"
            artwork.write_bytes(b"cached-artwork")
            with override_settings(MEDIA_LIBRARY_ARTWORK_ROOT=temporary):
                logo = VODLogo.objects.create(
                    name="Unused cached poster",
                    url=str(artwork),
                )
                with self.captureOnCommitCallbacks(execute=True):
                    delete_media_library_logo_if_unused(logo.id)

            self.assertFalse(VODLogo.objects.filter(id=logo.id).exists())
            self.assertFalse(artwork.exists())


class MediaLibraryLifecycleRegressionTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="media-library-regression-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_removed_local_location_retires_its_vod_relations(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            retained_path = root / "retained"
            removed_path = root / "removed"
            retained_path.mkdir()
            removed_path.mkdir()
            with override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=(str(root),)):
                source = MediaLibrarySource.objects.create(
                    name="Scoped local source",
                    provider_type=MediaLibrarySource.ProviderTypes.LOCAL,
                )
                retained = MediaLibraryLocation.objects.create(
                    source=source,
                    name="Retained",
                    path=str(retained_path),
                )
                removed = MediaLibraryLocation.objects.create(
                    source=source,
                    name="Removed",
                    path=str(removed_path),
                )
                account = ensure_integration_vod_account(source)
                retained_movie = Movie.objects.create(name="Retained movie")
                removed_movie = Movie.objects.create(name="Removed movie")
                M3UMovieRelation.objects.create(
                    m3u_account=account,
                    movie=retained_movie,
                    stream_id="local:retained",
                    custom_properties={
                        "provider_library_id": str(retained.public_id),
                    },
                )
                M3UMovieRelation.objects.create(
                    m3u_account=account,
                    movie=removed_movie,
                    stream_id="local:removed",
                    custom_properties={
                        "provider_library_id": str(removed.public_id),
                    },
                )

                with patch(
                    "apps.media_servers.api_views.queue_automatic_exports.delay"
                ), self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        f"/api/media-library/sources/{source.id}/",
                        {
                            "locations": [
                                {
                                    "id": str(retained.public_id),
                                    "name": retained.name,
                                    "path": retained.path,
                                    "content_type": retained.content_type,
                                    "include_subdirectories": True,
                                    "enabled": True,
                                }
                            ]
                        },
                        format="json",
                    )

            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(
                M3UMovieRelation.objects.filter(stream_id="local:retained").exists()
            )
            self.assertFalse(
                M3UMovieRelation.objects.filter(stream_id="local:removed").exists()
            )
            self.assertFalse(MediaLibraryLocation.objects.filter(id=removed.id).exists())

    def test_deselected_remote_library_retires_its_vod_relations(self):
        source = MediaLibrarySource.objects.create(
            name="Scoped Plex source",
            provider_type=MediaLibrarySource.ProviderTypes.PLEX,
            base_url="https://plex.example",
            api_token="secret",
            include_libraries=["movies-a", "movies-b"],
        )
        account = ensure_integration_vod_account(source)
        retained_movie = Movie.objects.create(name="Plex retained")
        removed_movie = Movie.objects.create(name="Plex removed")
        for movie, library_id in (
            (retained_movie, "movies-a"),
            (removed_movie, "movies-b"),
        ):
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id=f"plex:{library_id}",
                custom_properties={"provider_library_id": library_id},
            )

        with patch(
            "apps.media_servers.api_views.queue_automatic_exports.delay"
        ), self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"/api/media-library/sources/{source.id}/",
                {"include_libraries": ["movies-a"]},
                format="json",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(M3UMovieRelation.objects.filter(stream_id="plex:movies-a").exists())
        self.assertFalse(M3UMovieRelation.objects.filter(stream_id="plex:movies-b").exists())

    def test_disabled_target_rejects_export_without_creating_run(self):
        with tempfile.TemporaryDirectory() as temporary, override_settings(
            MEDIA_LIBRARY_EXPORT_ROOTS=(temporary,)
        ):
            target = MediaLibraryExportTarget.objects.create(
                name="Disabled target",
                enabled=False,
                output_root=temporary,
                playback_base_url="https://dispatcharr.example",
            )
            response = self.client.post(
                f"/api/media-library/export-targets/{target.id}/export/"
            )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(target.export_runs.exists())

    def test_disabled_target_worker_marks_previously_queued_run_failed(self):
        with tempfile.TemporaryDirectory() as temporary, override_settings(
            MEDIA_LIBRARY_EXPORT_ROOTS=(temporary,)
        ):
            target = MediaLibraryExportTarget.objects.create(
                name="Disabled queued target",
                enabled=False,
                output_root=temporary,
                playback_base_url="https://dispatcharr.example",
            )
            run = MediaLibraryExportRun.objects.create(
                target=target,
                status=MediaLibraryExportRun.Status.QUEUED,
            )
            result = refresh_selected_series_and_export.run(target.id, run.id)

        run.refresh_from_db()
        self.assertEqual(run.status, MediaLibraryExportRun.Status.FAILED)
        self.assertIn("disabled", result)

    def test_concatenated_episode_nfo_returns_every_root_and_no_wrong_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "Show.S01E01E02.mkv"
            video.write_bytes(b"video")
            nfo = video.with_suffix(".nfo")
            nfo.write_text(
                "<?xml version=\"1.0\"?><episodedetails><season>1</season><episode>1</episode>"
                "<title>One</title></episodedetails>"
                "<?xml version=\"1.0\"?><episodedetails><season>1</season><episode>2</episode>"
                "<title>Two</title></episodedetails>",
                encoding="utf-8",
            )
            entries, error = parse_nfo_episode_entries(str(nfo))
            missing, missing_error = find_episode_nfo_metadata(
                str(video), season_number=1, episode_number=3
            )

        self.assertIsNone(error)
        self.assertEqual([entry["title"] for entry in entries], ["One", "Two"])
        self.assertIsNone(missing)
        self.assertIn("requested season", missing_error)

    def test_vod_merges_transfer_media_library_export_selections(self):
        with tempfile.TemporaryDirectory() as temporary, override_settings(
            MEDIA_LIBRARY_EXPORT_ROOTS=(temporary,)
        ):
            target = MediaLibraryExportTarget.objects.create(
                name="Merge selections",
                output_root=temporary,
                playback_base_url="https://dispatcharr.example",
            )
            current_movie = Movie.objects.create(name="Current movie")
            selected_movie = Movie.objects.create(name="Selected movie", tmdb_id="101")
            target.selected_movies.add(selected_movie)
            handle_movie_id_conflicts(current_movie, None, "101", None)

            current_series = Series.objects.create(name="Current series")
            selected_series = Series.objects.create(name="Selected series", tmdb_id="202")
            target.selected_series.add(selected_series)
            handle_series_id_conflicts(current_series, None, "202", None)

        self.assertTrue(target.selected_movies.filter(id=current_movie.id).exists())
        self.assertTrue(target.selected_series.filter(id=current_series.id).exists())

    def test_semantic_vod_failures_do_not_count_as_success(self):
        self.assertFalse(_vod_task_result_succeeded("VOD refresh failed: unavailable"))
        self.assertFalse(_vod_task_result_succeeded({"error": "unavailable"}))
        self.assertFalse(_vod_task_result_succeeded({"refreshed": 1, "failed": 1}))
        self.assertTrue(_vod_task_result_succeeded({"refreshed": 2, "failed": 0}))
        sender = SimpleNamespace(name="apps.vod.tasks.refresh_vod_content")
        with patch(
            "apps.media_servers.export_tasks.queue_automatic_exports.delay"
        ) as queued:
            queue_export_after_vod_task(
                sender=sender,
                state="SUCCESS",
                retval="VOD refresh failed: unavailable",
            )
        queued.assert_not_called()

    def test_dvr_nfo_metadata_and_local_artwork_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "Rich Movie (2026).mkv"
            video.write_bytes(b"video")
            video.with_suffix(".nfo").write_text(
                """<movie><title>Rich Movie</title><year>2026</year>
<director>Director One</director><credits>Writer One</credits>
<actor><name>Actor One</name><role>Lead</role></actor>
<mpaa>TV-14</mpaa><studio>Example Channel</studio><country>US</country>
<language>en</language><uniqueid type="schedulesdirect">EP123</uniqueid></movie>""",
                encoding="utf-8",
            )
            poster = root / "poster.jpg"
            poster.write_bytes(b"poster")
            artwork_root = root / "artwork"
            artwork_root.mkdir()
            export_root = root / "export"
            export_root.mkdir()
            source = ensure_dvr_media_library_source()

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ), override_settings(
                MEDIA_LIBRARY_IMPORT_ROOTS=("/unrelated",),
                MEDIA_LIBRARY_ARTWORK_ROOT=str(artwork_root),
                MEDIA_LIBRARY_EXPORT_ROOTS=(str(root),),
            ), patch(
                "apps.media_servers.providers.enrich_movie_metadata_with_tmdb",
                side_effect=lambda metadata, **_kwargs: (metadata, None),
            ):
                metadata, error = find_movie_nfo_metadata(str(video))
                cached = _cache_artwork(source, str(poster))
                with DVRClient(source) as provider:
                    movies, series_entries = provider.inspect_recording(str(video))
                movie, _created, _updated = _sync_movie(source, movies[0])
                account = ensure_integration_vod_account(source)
                M3UMovieRelation.objects.create(
                    m3u_account=account,
                    movie=movie,
                    stream_id="dvr:rich-movie",
                    custom_properties={
                        "managed_source": "media_server",
                        "provider": "dvr",
                        "file_path": str(video),
                    },
                )
                target = MediaLibraryExportTarget.objects.create(
                    name="Rich DVR export",
                    output_root=str(export_root),
                    playback_base_url="https://dispatcharr.example",
                )
                target.selected_movies.add(movie)
                build_strm_nfo_snapshot(target)
                exported_nfo = next(export_root.rglob("*.nfo")).read_text(
                    encoding="utf-8"
                )

            self.assertIsNone(error)
            self.assertEqual(metadata["custom_properties"]["studio"], "Example Channel")
            self.assertEqual(metadata["custom_properties"]["actors"][0]["role"], "Lead")
            self.assertTrue(Path(cached).is_file())
            self.assertFalse(series_entries)
            self.assertEqual(movie.custom_properties["age"], "TV-14")
            self.assertEqual(
                movie.custom_properties["unique_ids"]["schedulesdirect"],
                "EP123",
            )
            self.assertIn("<director>Director One</director>", exported_nfo)
            self.assertIn("<role>Lead</role>", exported_nfo)
            self.assertIn("<language>en</language>", exported_nfo)
            self.assertIn('type="schedulesdirect"', exported_nfo)

    def test_deleting_one_dvr_file_removes_only_its_relations(self):
        source = ensure_dvr_media_library_source()
        account = ensure_integration_vod_account(source)
        removed_movie = Movie.objects.create(name="Deleted recording")
        retained_movie = Movie.objects.create(name="Other recording")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=removed_movie,
            stream_id="dvr:deleted",
            custom_properties={"file_path": "/recordings/deleted.mkv"},
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=retained_movie,
            stream_id="dvr:retained",
            custom_properties={"file_path": "/recordings/retained.mkv"},
        )
        lock = SimpleNamespace(acquire=lambda **_kwargs: True, release=lambda: None)

        with patch(
            "apps.media_servers.tasks.RedisClient.get_client"
        ) as redis_client, patch(
            "apps.media_servers.export_tasks.queue_automatic_exports.delay"
        ) as queued:
            redis_client.return_value.lock.return_value = lock
            result = remove_dvr_media_library_recording.run(
                "/recordings/deleted.mkv"
            )

        self.assertFalse(M3UMovieRelation.objects.filter(stream_id="dvr:deleted").exists())
        self.assertTrue(M3UMovieRelation.objects.filter(stream_id="dvr:retained").exists())
        queued.assert_called_once_with("dvr-recording-deleted")
        self.assertIn("1 DVR relation", result)


class DVRMediaLibraryTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="dvr-media-library-admin",
            password="test",
            user_level=User.UserLevel.ADMIN,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_source_list_creates_permanent_dvr_card_and_rejects_delete(self):
        MediaLibrarySource.objects.filter(
            provider_type=MediaLibrarySource.ProviderTypes.DVR
        ).delete()

        response = self.client.get("/api/media-library/sources/")
        self.assertEqual(response.status_code, 200, response.content)
        dvr_source = next(
            entry for entry in response.json() if entry["provider_type"] == "dvr"
        )
        self.assertEqual(dvr_source["name"], "DVR")
        self.assertTrue(dvr_source["system_managed"])
        self.assertEqual(dvr_source["library_path"], "/data/recordings")

        disabled = self.client.patch(
            f"/api/media-library/sources/{dvr_source['id']}/",
            {"enabled": False},
            format="json",
        )
        self.assertEqual(disabled.status_code, 200, disabled.content)
        self.assertFalse(disabled.json()["enabled"])

        renamed = self.client.patch(
            f"/api/media-library/sources/{dvr_source['id']}/",
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(renamed.status_code, 400, renamed.content)

        deleted = self.client.delete(
            f"/api/media-library/sources/{dvr_source['id']}/"
        )
        self.assertEqual(deleted.status_code, 405, deleted.content)
        self.assertTrue(
            MediaLibrarySource.objects.filter(id=dvr_source["id"]).exists()
        )

    def test_existing_dvr_source_and_vod_account_are_renamed_in_place(self):
        source = ensure_dvr_media_library_source()
        account = ensure_integration_vod_account(source)
        source.name = "Media Library"
        source.save(update_fields=["name", "updated_at"])
        account.name = f"Media Library {source.id}: Media Library"
        account.custom_properties = {
            **(account.custom_properties or {}),
            "integration_name": "Media Library",
        }
        account.save(update_fields=["name", "custom_properties"])

        normalized = ensure_dvr_media_library_source()

        self.assertEqual(normalized.id, source.id)
        self.assertEqual(normalized.name, "DVR")
        account.refresh_from_db()
        self.assertEqual(account.name, f"Media Library {source.id}: DVR")
        self.assertEqual(account.custom_properties["integration_name"], "DVR")

    def test_dvr_client_reuses_local_importer_without_general_import_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            movie_file = root / "Movies" / "Unstoppable (2010).mp4"
            movie_file.parent.mkdir()
            movie_file.write_bytes(b"recording")
            source = ensure_dvr_media_library_source()

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ), override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=("/unrelated",)), patch(
                "apps.media_servers.providers.enrich_movie_metadata_with_tmdb",
                side_effect=lambda metadata, **kwargs: (metadata, None),
            ):
                with DVRClient(source) as client:
                    client.ping()
                    libraries = client.list_libraries()
                    movies = list(client.iter_movies(libraries))

            self.assertEqual(len(libraries), 1)
            self.assertEqual(len(movies), 1)
            self.assertEqual(movies[0].title, "Unstoppable")
            self.assertEqual(movies[0].local_path, str(movie_file.resolve()))

    def test_dvr_recording_playback_uses_dvr_root_not_general_import_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recording = root / "Movies" / "Recorded Movie (2026).mkv"
            recording.parent.mkdir()
            recording.write_bytes(b"recording")
            source = ensure_dvr_media_library_source()
            account = ensure_integration_vod_account(source)
            movie = Movie.objects.create(name="Recorded Movie", year=2026)
            relation = M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=movie,
                stream_id="dvr-recording",
                custom_properties={
                    "managed_source": "media_server",
                    "integration_id": source.id,
                    "provider": MediaLibrarySource.ProviderTypes.DVR,
                    "file_path": str(recording),
                },
            )

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ), override_settings(MEDIA_LIBRARY_IMPORT_ROOTS=("/unrelated",)):
                stream_url = _get_stream_url_from_relation(relation)
                manager_path = (
                    MultiWorkerVODConnectionManager._revalidate_local_media_path(
                        str(recording),
                        relation,
                    )
                )

            self.assertEqual(stream_url, f"file://{recording.resolve()}")
            self.assertEqual(manager_path, str(recording.resolve()))

    def test_dvr_episode_sidecar_supplies_series_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recording = root / "TVShows" / "S02E06.mkv"
            recording.parent.mkdir()
            recording.write_bytes(b"recording")
            recording.with_suffix(".nfo").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<episodedetails>
  <title>The Sixth Episode</title>
  <showtitle>Actual Show</showtitle>
  <showyear>2026</showyear>
  <plot>Recorded episode description.</plot>
  <season>2</season>
  <episode>6</episode>
  <durationinseconds>733</durationinseconds>
  <thumb aspect="poster">https://image.tmdb.org/t/p/original/show.jpg</thumb>
</episodedetails>
""",
                encoding="utf-8",
            )
            source = ensure_dvr_media_library_source()

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ), patch(
                "apps.media_servers.providers.enrich_series_metadata_with_tmdb",
                side_effect=lambda metadata, **kwargs: (metadata, None),
            ), patch(
                "apps.media_servers.providers.enrich_episode_metadata_with_tmdb",
                side_effect=lambda metadata, **kwargs: (metadata, None),
            ):
                with DVRClient(source) as client:
                    series = list(client.iter_series(client.list_libraries()))

            self.assertEqual(len(series), 1)
            self.assertEqual(series[0].title, "Actual Show")
            self.assertEqual(series[0].year, 2026)
            self.assertEqual(
                series[0].poster_url,
                "https://image.tmdb.org/t/p/original/show.jpg",
            )
            self.assertEqual(series[0].episodes[0].title, "The Sixth Episode")
            self.assertEqual(series[0].episodes[0].season_number, 2)
            self.assertEqual(series[0].episodes[0].episode_number, 6)
            self.assertEqual(series[0].episodes[0].duration_secs, 733)

    def test_completed_recording_queues_dvr_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "Movies" / "Recorded Movie (2026).mkv"
            output.parent.mkdir()
            output.write_bytes(b"recording")
            source = ensure_dvr_media_library_source()
            recording = SimpleNamespace(
                id=99,
                custom_properties={
                    "status": "completed",
                    "file_path": str(output),
                },
            )
            recording_queryset = SimpleNamespace(first=lambda: recording)
            lock = SimpleNamespace(
                acquire=lambda **_kwargs: True,
                release=lambda: None,
            )
            provider_movie = ProviderMovie(
                external_id="single-recording",
                title="Recorded Movie",
                category_name="DVR recordings",
                stream_url="",
                year=2026,
                local_path=str(output),
                local_file_name=output.name,
                local_file_size=output.stat().st_size,
                library_id="dvr-recordings",
            )

            with patch(
                "apps.media_servers.dvr_library.CoreSettings.get_dvr_library_dir",
                return_value=str(root),
            ), patch(
                "apps.channels.models.Recording.objects.select_related",
                return_value=SimpleNamespace(
                    filter=lambda **_kwargs: recording_queryset
                ),
            ), patch(
                "apps.media_servers.tasks._refresh_managed_recording_nfo"
            ), patch(
                "apps.media_servers.tasks.RedisClient.get_client"
            ) as redis_client, patch(
                "apps.media_servers.providers.DVRClient.inspect_recording",
                return_value=([provider_movie], []),
            ) as inspected, patch(
                "apps.media_servers.export_tasks.queue_automatic_exports.delay"
            ):
                redis_client.return_value.lock.return_value = lock
                result = sync_dvr_media_library_after_recording.run(99)

            inspected.assert_called_once_with(str(output.resolve()))
            source.refresh_from_db()
            relation = M3UMovieRelation.objects.get(m3u_account=source.vod_account)
            self.assertEqual(relation.custom_properties["file_path"], str(output))
            self.assertIn("DVR recording 99 imported", result)
