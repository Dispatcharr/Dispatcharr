from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.m3u.models import M3UAccount
from core.models import CoreSettings
from apps.output.views import xc_get_vod_categories, xc_get_vod_streams
from apps.vod.metadata import (
    category_defaults_for_relation,
    compatible_video_features,
    initialize_relation_metadata,
    initialize_relations_metadata,
    detect_video_features,
    effective_relation_metadata,
    normalize_language_list,
    relation_declared_metadata,
)
from apps.vod.playback import episode_history_name, record_playback_selection
from apps.vod.serializers import (
    M3USeriesRelationSerializer,
    VODAccessPolicySerializer,
    VODPlaybackSessionSerializer,
)
from apps.vod.models import (
    M3UMovieRelation,
    M3UEpisodeRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
    Movie,
    Episode,
    Series,
    VODAccessPolicy,
    VODCatalogState,
    VODMovieProfileSelection,
    VODPlaybackSession,
    VODPolicyCategory,
    VODCategory,
)
from apps.vod.policies import (
    allowed_category_query,
    ordered_candidates,
    ordered_failover_candidates,
    relation_allowed,
    relation_policy_evaluation,
    select_relation_ids_for_policy,
    select_relations_for_policy,
)
from apps.vod.api_views import (
    _vod_relation_sql,
    MovieViewSet,
    UnifiedContentViewSet,
    VODPlaybackSessionViewSet,
    VODSourceRelationViewSet,
    VODAccessPolicyViewSet,
)
from apps.vod.catalog_cache import (
    SELECTION_GENERATION_KEY,
    bump_catalog_generation,
    selection_catalog_generation,
)
from apps.vod.profile_selection import (
    PROFILE_REBUILD_ENQUEUE_KEY,
    ProfileBuildAlreadyRunning,
    _set_profile_progress,
    build_vod_profile_selection,
    enqueue_all_profile_selection_rebuilds,
    prepared_relation_ids,
)
from apps.vod.tasks import (
    VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY,
    _enqueue_deferred_profile_rebuild_after_vod_refreshes,
    _remember_profile_rebuild_after_vod_refresh,
    rebuild_all_vod_profile_selections,
    rebuild_vod_profile_selection,
    reconcile_vod_profile_selection_queue,
)
from apps.vod.utils import policy_output_name


class VODSourceManagementTests(TestCase):
    def setUp(self):
        self.movie = Movie.objects.create(name="Avatar", year=2005)
        self.german = VODCategory.objects.create(
            name="GERMANY KINDER", category_type="movie"
        )
        self.english = VODCategory.objects.create(
            name="NETFLIX ANIME", category_type="movie"
        )
        self.account_a = M3UAccount.objects.create(
            name="provider-a",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example",
            username="a",
            password="secret",
            priority=1,
        )
        self.account_b = M3UAccount.objects.create(
            name="provider-b",
            account_type=M3UAccount.Types.XC,
            server_url="https://provider.example",
            username="b",
            password="secret",
            priority=10,
        )
        self.german_category = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_a,
            category=self.german,
            enabled=True,
            metadata_defaults={
                "audio_languages": ["deu"],
                "resolution": "1080p",
            },
        )
        self.english_category = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_b,
            category=self.english,
            enabled=True,
            metadata_defaults={
                "audio_languages": ["eng"],
                "resolution": "2160p",
            },
        )
        self.german_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account_a,
            movie=self.movie,
            category=self.german,
            stream_id="42",
        )
        self.english_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account_b,
            movie=self.movie,
            category=self.english,
            stream_id="42",
        )
        self.policy = VODAccessPolicy.objects.create(
            name="German only",
            export_mode=VODAccessPolicy.ExportMode.COMPACT,
            hard_constraints={
                "required_audio_languages": ["deu"],
                "allow_unknown_metadata": False,
            },
            ranking=["audio_language", "subtitle_language", "resolution"],
        )

    def test_failover_never_uses_disallowed_language(self):
        ordered = ordered_failover_candidates(
            [self.english_relation, self.german_relation],
            self.policy,
        )
        self.assertEqual([relation.id for relation in ordered], [self.german_relation.id])

    def test_profile_category_import_rules_apply_to_existing_and_future_groups(self):
        self.policy.hard_constraints = {
            "source_rules": [],
            "category_import_rules": [
                {
                    "id": "hindi-categories",
                    "scope": "movie",
                    "m3u_account_id": None,
                    "match_field": "group_name",
                    "regex_pattern": "GERMANY|HINDI",
                    "action": "enable",
                    "case_sensitive": False,
                    "enabled": True,
                    "order": 0,
                }
            ],
        }

        self.assertTrue(relation_allowed(self.german_relation, self.policy))
        self.assertFalse(relation_allowed(self.english_relation, self.policy))

        hindi = VODCategory.objects.create(
            name="HINDI MOVIES", category_type="movie"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_b,
            category=hindi,
            enabled=True,
        )
        hindi_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account_b,
            movie=self.movie,
            category=hindi,
            stream_id="future-hindi",
        )
        bump_catalog_generation()

        self.assertTrue(relation_allowed(hindi_relation, self.policy))

    def test_profile_category_rule_can_be_scoped_to_one_provider(self):
        self.policy.hard_constraints = {
            "category_import_rules": [
                {
                    "id": "provider-a-only",
                    "scope": "movie",
                    "m3u_account_id": self.account_a.id,
                    "match_field": "group_name",
                    "regex_pattern": ".*",
                    "action": "enable",
                }
            ],
        }

        self.assertTrue(relation_allowed(self.german_relation, self.policy))
        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_explicit_profile_category_choice_overrides_dynamic_rule(self):
        self.policy.hard_constraints = {
            "category_import_rules": [
                {
                    "id": "allow-all",
                    "scope": "movie",
                    "match_field": "group_name",
                    "regex_pattern": ".*",
                    "action": "enable",
                }
            ],
        }
        VODPolicyCategory.objects.create(
            policy=self.policy,
            category_relation=self.german_category,
            enabled=False,
        )

        self.assertFalse(relation_allowed(self.german_relation, self.policy))
        self.assertTrue(relation_allowed(self.english_relation, self.policy))

    def test_dynamic_profile_cannot_restore_globally_disabled_category(self):
        self.policy.hard_constraints = {
            "category_import_rules": [
                {
                    "id": "allow-all",
                    "scope": "movie",
                    "match_field": "group_name",
                    "regex_pattern": ".*",
                    "action": "enable",
                }
            ],
        }
        self.english_category.enabled = False
        self.english_category.save(update_fields=["enabled"])
        bump_catalog_generation()

        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_dynamic_profile_can_block_every_globally_enabled_category(self):
        self.policy.hard_constraints = {"category_import_rules": []}

        query = allowed_category_query(self.policy)

        self.assertFalse(
            M3UMovieRelation.objects.filter(query).exists()
        )

    def test_first_matching_category_rule_overrides_default_source_constraints(self):
        self.english_category.metadata_defaults = {
            "audio_languages": ["eng"],
            "subtitle_languages": ["ger"],
            "resolution": "1080p",
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "required_audio_languages": ["ger"],
            "allow_unknown_metadata": False,
            "source_rules": [
                {
                    "name": "German subtitles for anime",
                    "category_regex": "ANIME",
                    "enabled": True,
                    "required_audio_languages": [],
                    "required_subtitle_languages": ["ger"],
                    "language_match_mode": "all",
                    "allow_unknown_metadata": False,
                },
                {
                    "name": "Would reject if evaluated",
                    "category_regex": "NETFLIX",
                    "enabled": True,
                    "excluded_audio_languages": ["eng"],
                },
            ],
        }

        self.assertTrue(relation_allowed(self.english_relation, self.policy))
        self.assertTrue(relation_allowed(self.german_relation, self.policy))

    def test_category_rule_can_exclude_video_features(self):
        self.english_category.metadata_defaults = {
            "audio_languages": ["eng"],
            "subtitle_languages": ["ger"],
            "resolution": "2160p",
            "video_features": ["dv"],
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "allow_unknown_metadata": False,
            "source_rules": [
                {
                    "name": "No DV anime",
                    "category_regex": "ANIME",
                    "enabled": True,
                    "required_audio_languages": [],
                    "required_subtitle_languages": ["ger"],
                    "excluded_video_features": ["dv", "3d"],
                    "language_match_mode": "all",
                    "allow_unknown_metadata": False,
                }
            ],
        }

        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_ordered_stream_filters_use_first_matching_category_decision(self):
        self.policy.hard_constraints = {
            "source_rules": [
                {
                    "match_field": "category",
                    "regex_pattern": "GERMANY",
                    "required_audio_languages": ["ger"],
                    "result": "include",
                },
                {
                    "match_field": "category",
                    "regex_pattern": ".*",
                    "result": "exclude",
                },
            ]
        }

        self.assertTrue(relation_allowed(self.german_relation, self.policy))
        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_stream_filter_can_match_provider_specific_source_name(self):
        self.english_relation.custom_properties = {
            "basic_data": {"name": "| USA | Avatar"}
        }
        self.english_relation.save(update_fields=["custom_properties"])
        self.policy.hard_constraints = {
            "source_rules": [
                {
                    "match_field": "stream",
                    "regex_pattern": r"^\| USA \|",
                    "result": "exclude",
                }
            ]
        }

        self.assertTrue(relation_allowed(self.german_relation, self.policy))
        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_stream_filter_metadata_is_part_of_the_first_match(self):
        self.english_category.metadata_defaults = {
            "audio_languages": ["eng"],
            "subtitle_languages": ["ger"],
            "resolution": "1080p",
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "source_rules": [
                {
                    "match_field": "category",
                    "regex_pattern": "ANIME",
                    "required_subtitle_languages": ["ger"],
                    "result": "include",
                },
                {
                    "match_field": "category",
                    "regex_pattern": ".*",
                    "result": "exclude",
                },
            ]
        }

        self.assertTrue(relation_allowed(self.english_relation, self.policy))
        self.assertFalse(relation_allowed(self.german_relation, self.policy))

    def test_content_filter_uses_manual_source_metadata_before_category_defaults(self):
        source = initialize_relation_metadata(self.english_relation)
        self.english_relation.refresh_from_db()
        source.manual_metadata = {"audio_languages": ["hin"]}
        source.save(update_fields=["manual_metadata", "updated_at"])
        self.policy.hard_constraints = {
            "content_default_action": "exclude",
            "source_rules": [
                {
                    "id": "english-dub",
                    "match_field": "stream",
                    "regex_pattern": "",
                    "required_audio_languages": ["eng"],
                    "result": "include",
                }
            ],
        }

        self.assertFalse(relation_allowed(self.english_relation, self.policy))

        source.manual_metadata = {"audio_languages": ["eng"]}
        source.save(update_fields=["manual_metadata", "updated_at"])
        self.english_relation.refresh_from_db()

        self.assertTrue(relation_allowed(self.english_relation, self.policy))

    def test_content_filter_can_exclude_canonical_genre_for_every_source(self):
        self.movie.tmdb_metadata = {
            "genres": [{"id": 878, "name": "Science Fiction"}],
            "keywords": [{"id": 210024, "name": "anime"}],
        }
        self.movie.tmdb_status = "matched"
        self.movie.save(update_fields=["tmdb_metadata", "tmdb_status"])
        self.policy.hard_constraints = {
            "content_default_action": "include",
            "source_rules": [
                {
                    "id": "exclude-science-fiction",
                    "match_field": "stream",
                    "regex_pattern": "",
                    "required_genres": ["Science Fiction"],
                    "result": "exclude",
                }
            ],
        }

        self.assertFalse(relation_allowed(self.english_relation, self.policy))
        self.assertFalse(relation_allowed(self.german_relation, self.policy))

    def test_content_filter_can_match_missing_tmdb_id(self):
        self.policy.hard_constraints = {
            "content_default_action": "include",
            "source_rules": [
                {
                    "id": "exclude-missing-tmdb",
                    "match_field": "stream",
                    "regex_pattern": "",
                    "tmdb_mode": "missing",
                    "result": "exclude",
                }
            ],
        }

        self.assertFalse(relation_allowed(self.german_relation, self.policy))

        self.movie.tmdb_match_id = "19995"
        self.movie.save(update_fields=["tmdb_match_id"])

        self.assertTrue(relation_allowed(self.german_relation, self.policy))

    def test_failover_can_prefer_lower_resolution(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.ranking = [
            "resolution_asc",
            "audio_language",
            "subtitle_language",
            "metadata_completeness",
        ]
        self.policy.save(update_fields=["hard_constraints", "ranking", "updated_at"])

        ordered = ordered_failover_candidates(
            [self.english_relation, self.german_relation],
            self.policy,
        )

        self.assertEqual(
            [relation.id for relation in ordered],
            [self.german_relation.id, self.english_relation.id],
        )

    def test_failover_can_prefer_a_provider_per_profile(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.ranking = [
            "provider",
            "resolution_desc",
            "metadata_completeness",
        ]
        self.policy.provider_order = [self.account_a.id, self.account_b.id]
        self.policy.save(
            update_fields=[
                "hard_constraints",
                "ranking",
                "provider_order",
                "updated_at",
            ]
        )

        ordered = ordered_failover_candidates(
            [self.english_relation, self.german_relation],
            self.policy,
        )

        self.assertEqual(
            [relation.id for relation in ordered],
            [self.german_relation.id, self.english_relation.id],
        )

    def test_provider_preference_respects_its_failover_position(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.ranking = [
            "resolution_desc",
            "provider",
            "metadata_completeness",
        ]
        self.policy.provider_order = [self.account_a.id, self.account_b.id]
        self.policy.save(
            update_fields=[
                "hard_constraints",
                "ranking",
                "provider_order",
                "updated_at",
            ]
        )

        ordered = ordered_failover_candidates(
            [self.german_relation, self.english_relation],
            self.policy,
        )

        self.assertEqual(
            [relation.id for relation in ordered],
            [self.english_relation.id, self.german_relation.id],
        )

    def test_failover_can_place_unknown_metadata_last(self):
        self.german_category.metadata_defaults = {}
        self.german_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.ranking = [
            "metadata_completeness",
            "audio_language",
            "subtitle_language",
            "resolution_desc",
        ]
        self.policy.save(update_fields=["hard_constraints", "ranking", "updated_at"])

        ordered = ordered_failover_candidates(
            [self.german_relation, self.english_relation],
            self.policy,
        )

        self.assertEqual(
            [relation.id for relation in ordered],
            [self.english_relation.id, self.german_relation.id],
        )

    def test_language_aliases_use_english_iso_639_2_b_codes(self):
        self.assertEqual(
            normalize_language_list(["deu", "de", "Deutsch", "eng"]),
            ["ger", "eng"],
        )

    def test_category_allowlist_and_audio_or_subtitle_policy(self):
        self.english_category.metadata_defaults = {
            "audio_languages": ["eng"],
            "subtitle_languages": ["ger"],
            "resolution": "1080p",
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "required_audio_languages": ["ger"],
            "required_subtitle_languages": ["ger"],
            "language_match_mode": "any",
            "allow_unknown_metadata": False,
        }
        self.policy.save(update_fields=["hard_constraints", "updated_at"])
        VODPolicyCategory.objects.create(
            policy=self.policy,
            category_relation=self.english_category,
            enabled=True,
        )

        self.assertTrue(relation_allowed(self.english_relation, self.policy))
        self.assertFalse(relation_allowed(self.german_relation, self.policy))

    def test_audio_or_subtitle_does_not_accept_a_known_mismatch_plus_unknown(self):
        self.english_category.metadata_defaults = {
            "audio_languages": ["eng"],
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "required_audio_languages": ["ger"],
            "required_subtitle_languages": ["ger"],
            "language_match_mode": "any",
            "allow_unknown_metadata": True,
        }
        self.policy.save(update_fields=["hard_constraints", "updated_at"])

        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_resolution_constraints_use_vertical_resolution_names(self):
        self.policy.hard_constraints = {
            "min_resolution": 720,
            "max_resolution": 1080,
            "allow_unknown_metadata": False,
        }
        self.policy.save(update_fields=["hard_constraints", "updated_at"])

        self.assertTrue(relation_allowed(self.german_relation, self.policy))
        self.assertFalse(relation_allowed(self.english_relation, self.policy))

    def test_series_technical_sql_can_match_episode_metadata_and_format(self):
        joins, conditions, params, canonical_column = _vod_relation_sql(
            {
                "audio_language": "deu",
                "subtitle_language": "ger",
                "resolution": "1080p",
                "container_extension": "mkv",
            },
            "series",
        )

        sql = " ".join(conditions)
        self.assertEqual(canonical_column, "series_id")
        self.assertIn("vod_m3useriesrelation", joins)
        self.assertIn("vod_m3uepisoderelation", sql)
        self.assertIn("episode_relation.container_extension", sql)
        for value in ("ger", "1080p", "mkv"):
            self.assertIn(value, params)
        self.assertNotIn("deu", params)

    def test_episode_inherits_defaults_from_its_series_category(self):
        series = Series.objects.create(name="Avatar Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=self.german,
            external_series_id="avatar-series",
        )
        episode = Episode.objects.create(
            series=series,
            name="Episode 1",
            season_number=1,
            episode_number=1,
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="avatar-episode-1",
        )

        self.assertEqual(
            category_defaults_for_relation(episode_relation)["audio_languages"],
            ["deu"],
        )

    def test_fast_catalog_container_is_declared_source_metadata(self):
        self.german_relation.container_extension = "MKV"
        self.german_relation.save(update_fields=["container_extension"])

        self.assertEqual(
            relation_declared_metadata(self.german_relation)[
                "container_extension"
            ],
            "mkv",
        )

    def test_legacy_manual_container_does_not_override_provider_format(self):
        self.german_relation.container_extension = "mkv"
        self.german_relation.save(update_fields=["container_extension"])
        source = initialize_relation_metadata(self.german_relation)
        source.manual_metadata = {"container_extension": "mp4"}
        source.locked_fields = ["container_extension"]
        source.save(update_fields=["manual_metadata", "locked_fields"])

        effective = source.effective_metadata(
            relation_declared=relation_declared_metadata(self.german_relation)
        )

        self.assertEqual(effective["values"]["container_extension"], "mkv")
        self.assertEqual(effective["provenance"]["container_extension"], "relation")

    def test_provider_track_metadata_is_not_treated_as_complete_source_metadata(self):
        self.german_relation.custom_properties = {
            "detailed_info": {
                "bitrate": 8000,
                "video": {
                    "codec_name": "hevc",
                    "width": 1920,
                    "height": 1080,
                    "avg_frame_rate": "24000/1001",
                    "bit_rate": "8000000",
                },
                "audio": {
                    "codec_name": "eac3",
                    "tags": {"language": "deu"},
                },
                "subtitles": [{"tags": {"language": "eng"}}],
            },
            "movie_data": {"size": "1.5 GiB"},
        }

        metadata = relation_declared_metadata(self.german_relation)

        self.assertEqual(metadata["bitrate_kbps"], 8000)
        self.assertEqual(metadata["file_size_bytes"], 1610612736)
        for field in (
            "video_codec",
            "audio_codec",
            "audio_languages",
            "subtitle_languages",
            "resolution",
        ):
            self.assertNotIn(field, metadata)

    def test_episode_uses_valid_provider_video_resolution_and_codec(self):
        series = Series.objects.create(name="Provider Video Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=self.german,
            external_series_id="provider-video-series",
        )
        episode = Episode.objects.create(
            series=series,
            name="Episode 1",
            season_number=1,
            episode_number=1,
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="provider-video-episode",
            custom_properties={
                "info": {
                    "info": {
                        "video": {
                            "codec_name": "h264",
                            "width": 1920,
                            "height": 960,
                        },
                        "audio": {
                            "codec_name": "eac3",
                            "tags": {"language": "deu"},
                        },
                    }
                }
            },
        )

        metadata = effective_relation_metadata(relation)

        self.assertEqual(metadata["values"]["resolution"], "1080p")
        self.assertEqual(metadata["values"]["video_codec"], "h264")
        self.assertEqual(metadata["provenance"]["resolution"], "relation")
        self.assertNotIn("audio_codec", metadata["values"])
        self.assertEqual(metadata["values"]["audio_languages"], ["ger"])
        self.assertEqual(
            metadata["provenance"]["audio_languages"],
            "series_category",
        )

    def test_episode_image_video_payload_falls_back_to_category_resolution(self):
        series = Series.objects.create(name="Provider Cover Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=self.german,
            external_series_id="provider-cover-series",
        )
        episode = Episode.objects.create(
            series=series,
            name="Episode 1",
            season_number=1,
            episode_number=1,
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="provider-cover-episode",
            custom_properties={
                "info": {
                    "info": {
                        "video": {
                            "codec_name": "png",
                            "width": 1000,
                            "height": 1500,
                        }
                    }
                }
            },
        )

        metadata = effective_relation_metadata(relation)

        self.assertEqual(metadata["values"]["resolution"], "1080p")
        self.assertEqual(metadata["provenance"]["resolution"], "series_category")
        self.assertNotIn("video_codec", metadata["values"])

    def test_series_source_summarizes_valid_episode_video_metadata(self):
        series = Series.objects.create(name="Provider Summary Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=self.german,
            external_series_id="provider-summary-series",
        )
        episode_relations = []
        for number, codec, width, height in (
            (1, "h264", 1920, 960),
            (2, "hevc", 1280, 720),
            (3, "png", 1000, 1500),
        ):
            episode = Episode.objects.create(
                series=series,
                name=f"Episode {number}",
                season_number=1,
                episode_number=number,
            )
            episode_relations.append(
                M3UEpisodeRelation.objects.create(
                    m3u_account=self.account_a,
                    episode=episode,
                    series_relation=series_relation,
                    stream_id=f"provider-summary-{number}",
                    custom_properties={
                        "info": {
                            "info": {
                                "video": {
                                    "codec_name": codec,
                                    "width": width,
                                    "height": height,
                                }
                            }
                        }
                    },
                )
            )
        series_relation.metadata_episode_relations = episode_relations

        payload = M3USeriesRelationSerializer(
            series_relation,
            context={"include_episode_technical_summary": True},
        ).data["source_metadata"]

        self.assertEqual(
            payload["values"]["episode_resolutions"],
            ["720p", "1080p"],
        )
        self.assertEqual(
            payload["values"]["episode_video_codecs"],
            ["h264", "hevc"],
        )

    def test_video_features_are_detected_and_can_bound_a_profile(self):
        self.assertEqual(
            detect_video_features("Movie.3D.HSBS.HDR10+.mkv"),
            ["3d", "hdr"],
        )
        self.german_category.metadata_defaults = {
            "video_features": ["3d", "hdr"]
        }
        self.german_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "required_video_features": ["3d"],
            "allow_unknown_metadata": False,
        }
        self.policy.save(update_fields=["hard_constraints", "updated_at"])

        self.assertTrue(relation_allowed(self.german_relation, self.policy))
        self.assertFalse(relation_allowed(self.english_relation, self.policy))
        self.assertEqual(compatible_video_features("hdr"), ["hdr"])

    def test_profile_exclusions_override_allowed_languages_and_features(self):
        self.german_category.metadata_defaults = {
            "audio_languages": ["ger"],
            "subtitle_languages": ["eng"],
            "video_features": ["3d"],
        }
        self.german_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "required_audio_languages": ["ger"],
            "excluded_subtitle_languages": ["eng"],
            "excluded_video_features": ["3d"],
            "allow_unknown_metadata": True,
        }
        self.policy.save(update_fields=["hard_constraints", "updated_at"])

        self.assertFalse(relation_allowed(self.german_relation, self.policy))

    def test_legacy_bitrate_ranking_does_not_affect_failover(self):
        self.english_relation.custom_properties = {
            "detailed_info": {"bitrate": 9000}
        }
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.ranking = ["bitrate_asc", "metadata_completeness"]
        self.policy.save(update_fields=["hard_constraints", "ranking", "updated_at"])

        ordered = ordered_failover_candidates(
            [self.german_relation, self.english_relation],
            self.policy,
        )

        self.assertEqual(
            [relation.id for relation in ordered],
            [self.english_relation.id, self.german_relation.id],
        )

    def test_language_preference_wins_over_account_and_category_priority(self):
        self.policy.hard_constraints = {
            "required_audio_languages": ["ger", "eng"],
            "min_resolution": 720,
            "max_resolution": 2160,
            "allow_unknown_metadata": False,
        }
        self.policy.save(update_fields=["hard_constraints", "updated_at"])

        ordered = ordered_failover_candidates(
            [self.english_relation, self.german_relation], self.policy
        )

        self.assertEqual(ordered[0].id, self.german_relation.id)

    def test_provider_data_keeps_every_provider_relation_distinct(self):
        compact = select_relations_for_policy(
            [self.german_relation, self.english_relation],
            self.policy,
            "movie_id",
        )
        self.assertEqual([relation.id for relation in compact], [self.german_relation.id])

        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.save()
        variants = select_relations_for_policy(
            [self.german_relation, self.english_relation],
            self.policy,
            "movie_id",
        )
        self.assertEqual(len(variants), 2)

        initialize_relation_metadata(self.german_relation)
        initialize_relation_metadata(self.english_relation)
        self.german_relation.refresh_from_db()
        self.english_relation.refresh_from_db()
        still_independent = select_relations_for_policy(
            [self.german_relation, self.english_relation],
            self.policy,
            "movie_id",
        )
        self.assertEqual(len(still_independent), 2)

    def test_provider_data_playback_uses_only_the_selected_relation(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.save()

        ordered = ordered_candidates(
            [self.german_relation, self.english_relation],
            self.policy,
            preferred_relation=self.english_relation,
        )

        self.assertEqual(
            [relation.id for relation in ordered],
            [self.english_relation.id],
        )

    def test_streaming_compact_selection_returns_only_winner_ids(self):
        ids = select_relation_ids_for_policy(
            iter([self.english_relation, self.german_relation]),
            self.policy,
            "movie_id",
        )

        self.assertEqual(ids, [self.german_relation.id])

    def test_profile_build_materializes_compact_output_and_normalizes_metadata(self):
        self.policy.selection_progress = {
            "task_id": "profile-build-task",
            "task_name": "apps.vod.tasks.rebuild_vod_profile_selection",
            "queue": "celery",
            "trigger_reason": "Profile settings were saved",
        }
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_progress=self.policy.selection_progress
        )
        counts = build_vod_profile_selection(self.policy.id)

        self.policy.refresh_from_db()
        rows = VODMovieProfileSelection.objects.filter(
            policy=self.policy,
            generation=self.policy.active_selection_generation,
        )
        self.assertEqual(self.policy.selection_status, "ready")
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.get().relation_id, self.german_relation.id)
        self.assertEqual(rows.get().audio_languages, ["ger"])
        self.assertEqual(counts["movies"]["candidate_sources"], 2)
        self.assertEqual(counts["movies"]["eligible_sources"], 1)
        self.assertEqual(counts["movies"]["output_entries"], 1)
        self.assertEqual(counts["export_mode"], "compact")
        self.assertTrue(counts["profile_signature"])
        self.assertGreaterEqual(counts["prepared_seconds"], 0)
        self.assertEqual(self.policy.selection_progress["phase"], "Ready")
        self.assertEqual(self.policy.selection_progress["percent"], 100)
        self.assertEqual(self.policy.selection_progress["stage_index"], 5)
        self.assertEqual(
            self.policy.selection_progress["task_id"], "profile-build-task"
        )
        self.assertEqual(
            self.policy.selection_progress["trigger_reason"],
            "Profile settings were saved",
        )
        self.assertEqual(
            self.policy.selection_progress["target_export_mode"], "compact"
        )

    def test_compact_editions_are_visible_in_preview_and_xc_output(self):
        self.german_category.metadata_defaults = {
            **self.german_category.metadata_defaults,
            "video_features": ["3d"],
        }
        self.german_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.edition_rules = [
            {
                "id": "three-d",
                "name": "3D",
                "title_suffix": "3D",
                "enabled": True,
                "match_field": "any",
                "regex_pattern": "",
                "required_video_features": ["3d"],
            },
            {
                "id": "ultra-hd",
                "name": "UHD",
                "title_suffix": "4K",
                "enabled": True,
                "match_field": "any",
                "regex_pattern": "",
                "min_resolution": 2160,
            },
        ]
        self.policy.save(
            update_fields=[
                "hard_constraints",
                "edition_rules",
                "updated_at",
            ]
        )

        counts = build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        selections = VODMovieProfileSelection.objects.filter(
            policy=self.policy,
            generation=self.policy.active_selection_generation,
        ).order_by("edition_name")

        self.assertEqual(counts["movies"]["canonical_titles"], 1)
        self.assertEqual(counts["movies"]["output_entries"], 2)
        self.assertEqual(
            list(selections.values_list("edition_name", "output_name")),
            [
                ("3D", "Avatar (2005) 3D"),
                ("4K", "Avatar (2005) 4K"),
            ],
        )
        self.assertEqual(
            len(set(selections.values_list("category_id", flat=True))),
            1,
        )

        admin = get_user_model().objects.create_user(
            username="edition-preview-admin",
            password="test-password",
            user_level=10,
        )
        preview_request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {"type": "movie"},
        )
        force_authenticate(preview_request, user=admin)
        preview_response = VODAccessPolicyViewSet.as_view(
            {"get": "selections"}
        )(preview_request, pk=self.policy.id)

        self.assertEqual(preview_response.status_code, 200, preview_response.data)
        self.assertEqual(preview_response.data["count"], 2)
        self.assertEqual(
            {row["name"] for row in preview_response.data["results"]},
            {"Avatar (2005) 3D", "Avatar (2005) 4K"},
        )

        user = get_user_model().objects.create_user(
            username="edition-client",
            password="test-password",
        )
        self.policy.users.add(user)
        client_rows = xc_get_vod_streams(
            RequestFactory().get("/player_api.php"),
            user,
        )
        self.assertEqual(
            {row["name"] for row in client_rows},
            {"Avatar (2005) 3D", "Avatar (2005) 4K"},
        )

        failover = ordered_failover_candidates(
            [self.german_relation, self.english_relation],
            self.policy,
            preferred_relation=self.german_relation,
        )
        self.assertEqual(
            [relation.id for relation in failover],
            [self.german_relation.id],
        )

    def test_variants_support_formatted_clean_titles_and_ignore_suffix_rules(self):
        self.movie.clean_title = "Avatar"
        self.movie.save(update_fields=["clean_title"])
        self.german_category.metadata_defaults = {
            **self.german_category.metadata_defaults,
            "video_features": ["3d"],
        }
        self.german_category.save(update_fields=["metadata_defaults"])
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.naming_mode = VODAccessPolicy.NamingMode.TEMPLATE
        self.policy.name_template = "{title} ({year}) {provider}"
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.edition_rules = [
            {
                "id": "three-d",
                "name": "3D",
                "title_suffix": "3D",
                "enabled": True,
                "match_field": "any",
                "required_video_features": ["3d"],
            }
        ]
        self.german_relation.custom_properties = {
            "movie_data": {"name": "Provider A Avatar 3D"}
        }
        self.german_relation.save(update_fields=["custom_properties"])
        self.english_relation.custom_properties = {
            "movie_data": {"name": "Provider B Avatar UHD"}
        }
        self.english_relation.save(update_fields=["custom_properties"])
        self.policy.save()

        counts = build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        names = set(
            VODMovieProfileSelection.objects.filter(
                policy=self.policy,
                generation=self.policy.active_selection_generation,
            ).values_list("output_name", flat=True)
        )

        self.assertEqual(counts["movies"]["output_entries"], 2)
        self.assertEqual(
            names,
            {"Avatar (2005) provider-a", "Avatar (2005) provider-b"},
        )

    def test_canonical_title_falls_back_to_clean_then_provider_title(self):
        self.policy.naming_mode = VODAccessPolicy.NamingMode.TEMPLATE
        self.policy.name_template = "{title}"
        self.policy.canonical_title_source = (
            VODAccessPolicy.CanonicalTitleSource.SECONDARY
        )
        self.movie.clean_title = "Avatar Clean"
        self.movie.save(update_fields=["clean_title"])
        self.german_relation.custom_properties = {
            "movie_data": {"name": "Provider Avatar"}
        }

        self.assertEqual(
            policy_output_name(
                self.movie,
                self.german_relation,
                self.policy,
                canonical_languages=["de-DE", "en-US"],
            ),
            "Avatar Clean",
        )

        self.movie.clean_title = ""
        self.assertEqual(
            policy_output_name(
                self.movie,
                self.german_relation,
                self.policy,
                canonical_languages=["de-DE", "en-US"],
            ),
            "Provider Avatar",
        )

    def test_switching_variants_to_compact_activates_compact_generation(self):
        unrestricted = {"allow_unknown_metadata": True}
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            export_mode=VODAccessPolicy.ExportMode.VARIANTS,
            hard_constraints=unrestricted,
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
        )

        variant_counts = build_vod_profile_selection(self.policy.id)
        self.assertEqual(variant_counts["movies"]["output_entries"], 2)
        self.assertEqual(variant_counts["movies"]["canonical_titles"], 1)
        self.assertEqual(variant_counts["export_mode"], "variants")

        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            export_mode=VODAccessPolicy.ExportMode.COMPACT,
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
        )
        compact_counts = build_vod_profile_selection(self.policy.id)

        self.policy.refresh_from_db()
        self.assertEqual(compact_counts["movies"]["output_entries"], 1)
        self.assertEqual(compact_counts["movies"]["canonical_titles"], 1)
        self.assertEqual(compact_counts["export_mode"], "compact")
        self.assertEqual(
            self.policy.selection_counts["generation"],
            self.policy.active_selection_generation,
        )
        serialized = VODAccessPolicySerializer(self.policy).data
        self.assertEqual(serialized["selection_active_mode"], "compact")
        self.assertTrue(serialized["selection_current"])

    def test_legacy_variant_counts_are_not_current_for_compact_profile(self):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            active_selection_generation="legacy-generation",
            selection_catalog_generation=str(selection_catalog_generation()),
            selection_counts={
                "movies": {"output_entries": 2, "canonical_titles": 1},
                "series": {"output_entries": 0, "canonical_titles": 0},
            },
        )
        self.policy.refresh_from_db()

        serialized = VODAccessPolicySerializer(self.policy).data

        self.assertEqual(serialized["selection_active_mode"], "variants")
        self.assertFalse(serialized["selection_current"])

    def test_listing_profiles_trusts_a_completed_ready_lifecycle(self):
        admin = get_user_model().objects.create_user(
            username="profile-repair-admin",
            password="test-password",
            user_level=10,
        )
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            active_selection_generation="stale-generation",
            selection_catalog_generation="stale-source-generation",
        )
        request = APIRequestFactory().get("/api/vod/access-policies/")
        force_authenticate(request, user=admin)

        with patch(
            "apps.vod.profile_selection.enqueue_profile_selection_rebuild"
        ) as enqueue:
            response = VODAccessPolicyViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        serialized_policy = next(
            row for row in response.data if row["id"] == self.policy.pk
        )
        self.assertTrue(serialized_policy["selection_current"])
        enqueue.assert_not_called()

    def test_profile_build_does_not_overlap_an_active_build(self):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            selection_started_at=timezone.now(),
        )

        with self.assertRaises(ProfileBuildAlreadyRunning):
            build_vod_profile_selection(self.policy.id)

    def test_profile_progress_cannot_move_backwards_within_one_build(self):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            selection_progress={
                "phase": "Selecting movies sources",
                "percent": 20,
                "processed": 35000,
                "total": 83733,
                "stage_index": 1,
                "stage_count": 5,
                "build_generation": "active-build",
            },
        )

        updated = _set_profile_progress(
            self.policy.pk,
            "Selecting movies sources",
            10,
            processed=20000,
            total=83733,
            stage_index=1,
            stage_count=5,
            build_generation="active-build",
        )

        self.assertFalse(updated)
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.selection_progress["processed"], 35000)
        self.assertEqual(self.policy.selection_progress["percent"], 20)

    def test_profile_progress_percent_cannot_regress_when_phase_text_changes(self):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            selection_progress={
                "phase": "Selecting movies sources",
                "percent": 28,
                "processed": 65000,
                "total": 83733,
                "stage_index": 1,
                "stage_count": 5,
                "build_generation": "active-build",
            },
        )

        updated = _set_profile_progress(
            self.policy.pk,
            "Selecting movie sources",
            2,
            processed=0,
            total=83733,
            stage_index=1,
            stage_count=5,
            build_generation="active-build",
        )

        self.assertFalse(updated)
        self.policy.refresh_from_db()
        self.assertEqual(self.policy.selection_progress["processed"], 65000)
        self.assertEqual(self.policy.selection_progress["percent"], 28)

    @patch("core.utils.send_websocket_update")
    def test_profile_progress_pushes_each_persisted_batch(self, websocket_update):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            selection_progress={
                "phase": "Selecting movies sources",
                "percent": 2,
                "processed": 0,
                "total": 83733,
                "stage_index": 1,
                "stage_count": 5,
                "build_generation": "active-build",
            },
        )

        updated = _set_profile_progress(
            self.policy.pk,
            "Selecting movies sources",
            12,
            processed=25000,
            total=83733,
            stage_index=1,
            stage_count=5,
            build_generation="active-build",
        )

        self.assertTrue(updated)
        websocket_update.assert_called_once()
        payload = websocket_update.call_args.args[2]
        self.assertEqual(payload["type"], "vod_profile_selection")
        self.assertEqual(payload["profile_id"], self.policy.pk)
        self.assertEqual(payload["selection_status"], "building")
        self.assertEqual(payload["selection_progress"]["percent"], 12)

    def test_duplicate_task_does_not_rebuild_an_already_ready_profile(self):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            selection_progress={"phase": "Ready", "percent": 100},
        )

        result = rebuild_vod_profile_selection.run(self.policy.id)

        self.policy.refresh_from_db()
        self.assertIn("skipped", result)
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )
        self.assertEqual(self.policy.selection_progress["phase"], "Ready")

    def test_xc_uses_current_prepared_profile_without_cold_python_selection(self):
        user = get_user_model().objects.create_user(
            username="prepared-profile-user",
            password="test-password",
        )
        self.policy.users.add(user)
        build_vod_profile_selection(self.policy.id)
        request = RequestFactory().get("/player_api.php")

        with patch(
            "apps.vod.policies.select_relation_ids_for_policy",
            side_effect=AssertionError("cold selector should not run"),
        ):
            rows = xc_get_vod_streams(request, user)

        self.assertEqual(
            [row["stream_id"] for row in rows],
            [self.german_relation.id],
        )

    def test_catalog_change_keeps_last_prepared_generation_available(self):
        build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        self.assertIsNotNone(
            prepared_relation_ids(
                self.policy,
                M3UMovieRelation,
                {"m3u_account__is_active": True},
            )
        )

        bump_catalog_generation()

        self.assertEqual(
            prepared_relation_ids(
                self.policy,
                M3UMovieRelation,
                {"m3u_account__is_active": True},
            ),
            [self.german_relation.id],
        )

    def test_user_assignment_keeps_prepared_profile_current(self):
        build_vod_profile_selection(self.policy.id)
        user = get_user_model().objects.create_user(
            username="profile-assignment-user",
            password="test-password",
        )

        self.policy.users.add(user)
        self.policy.refresh_from_db()

        self.assertEqual(self.policy.selection_status, "ready")
        self.assertEqual(
            prepared_relation_ids(
                self.policy,
                M3UMovieRelation,
                {"m3u_account__is_active": True},
            ),
            [self.german_relation.id],
        )

    def test_account_runtime_status_keeps_prepared_profile_current(self):
        build_vod_profile_selection(self.policy.id)

        self.account_a.status = M3UAccount.Status.PARSING
        self.account_a.last_message = "Refreshing VOD metadata"
        self.account_a.save(update_fields=["status", "last_message"])
        self.policy.refresh_from_db()

        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )
        self.assertIsNotNone(
            prepared_relation_ids(
                self.policy,
                M3UMovieRelation,
                {"m3u_account__is_active": True},
            )
        )

    def test_account_runtime_full_save_keeps_prepared_profile_current(self):
        build_vod_profile_selection(self.policy.id)

        self.account_a.status = M3UAccount.Status.PARSING
        self.account_a.last_message = "Refreshing VOD metadata"
        self.account_a.save()
        self.policy.refresh_from_db()

        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )

    def test_episode_inventory_change_keeps_prepared_profile_current(self):
        build_vod_profile_selection(self.policy.id)
        series = Series.objects.create(name="Progress series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=self.german,
            external_series_id="progress-series",
        )
        episode = Episode.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            name="Pilot",
        )

        # The series relation itself changes selectable output and therefore
        # queues a rebuild. Complete that rebuild before testing the episode-only
        # inventory change.
        build_vod_profile_selection(self.policy.id)
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            series_relation=series_relation,
            episode=episode,
            stream_id="progress-episode",
        )
        self.policy.refresh_from_db()

        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )

    def test_canonical_metadata_refresh_keeps_prepared_profile_current(self):
        build_vod_profile_selection(self.policy.id)

        self.movie.description = "Updated provider description"
        self.movie.save(update_fields=["description"])
        self.policy.refresh_from_db()

        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )
        self.assertIsNotNone(
            prepared_relation_ids(
                self.policy,
                M3UMovieRelation,
                {"m3u_account__is_active": True},
            )
        )

    def test_account_priority_change_marks_prepared_profile_pending(self):
        build_vod_profile_selection(self.policy.id)

        self.account_a.priority = 50
        self.account_a.save(update_fields=["priority"])
        self.policy.refresh_from_db()

        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.PENDING,
        )

    def test_prepared_generation_survives_an_empty_runtime_cache(self):
        from django.core.cache import cache

        build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        expected = self.policy.selection_catalog_generation

        cache.delete(SELECTION_GENERATION_KEY)

        self.assertEqual(str(selection_catalog_generation()), expected)
        self.assertEqual(
            VODCatalogState.objects.get(pk=1).selection_generation,
            expected,
        )

    def test_durable_generation_wins_after_runtime_cache_restart(self):
        from django.core.cache import cache

        build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        expected = self.policy.selection_catalog_generation
        newer_policy = VODAccessPolicy.objects.create(
            name="Misleading newer completion",
            is_active=False,
        )
        VODAccessPolicy.objects.filter(pk=newer_policy.pk).update(
            selection_catalog_generation="not-the-source-generation",
            selection_completed_at=timezone.now() + timedelta(days=1),
        )

        cache.delete(SELECTION_GENERATION_KEY)

        self.assertEqual(str(selection_catalog_generation()), expected)

    def test_cache_restart_does_not_requeue_a_ready_profile(self):
        from django.core.cache import cache

        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_active=False
        )
        build_vod_profile_selection(self.policy.id)
        cache.delete(SELECTION_GENERATION_KEY)
        cache.delete(PROFILE_REBUILD_ENQUEUE_KEY)

        with patch(
            "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
        ) as enqueue:
            result = reconcile_vod_profile_selection_queue.run()

        self.policy.refresh_from_db()
        self.assertEqual(result["stale_ready_requeued"], 0)
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )
        enqueue.assert_not_called()

    def test_watchdog_does_not_second_guess_a_ready_source_generation(self):
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_active=False
        )
        build_vod_profile_selection(self.policy.id)
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_catalog_generation="previous-source-marker"
        )

        with patch(
            "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
        ) as enqueue:
            result = reconcile_vod_profile_selection_queue.run()

        self.policy.refresh_from_db()
        self.assertEqual(result["stale_ready_requeued"], 0)
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )
        enqueue.assert_not_called()

    def test_watchdog_does_not_treat_code_signature_as_a_profile_save(self):
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_active=False
        )
        build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        counts = {**self.policy.selection_counts}
        counts["profile_signature"] = "prepared-by-an-older-version"
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_counts=counts
        )

        with patch(
            "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
        ) as enqueue:
            result = reconcile_vod_profile_selection_queue.run()

        self.policy.refresh_from_db()
        self.assertEqual(result["stale_ready_requeued"], 0)
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.READY,
        )
        self.assertTrue(
            VODAccessPolicySerializer(self.policy).data["selection_current"]
        )
        enqueue.assert_not_called()

    def test_live_refresh_account_metadata_does_not_rebuild_vod_profiles(self):
        self.account_a.custom_properties = {
            **(self.account_a.custom_properties or {}),
            "live_catalog_counts": {
                "provider_total": 120,
                "selected_total": 100,
            },
            "refresh_timings": {
                "live_seconds": 4.2,
                "live_completed_at": timezone.now().isoformat(),
            },
        }

        with patch(
            "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
        ) as enqueue:
            self.account_a.save(update_fields=["custom_properties"])

        enqueue.assert_not_called()

    def test_vod_account_setting_still_rebuilds_vod_profiles(self):
        self.account_a.custom_properties = {
            **(self.account_a.custom_properties or {}),
            "enable_vod": True,
        }

        with patch(
            "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
        ) as enqueue:
            self.account_a.save(update_fields=["custom_properties"])

        enqueue.assert_called_once_with(
            trigger_reason="M3U account VOD selection settings changed"
        )

    def test_source_observation_marks_profiles_outdated(self):
        source = initialize_relation_metadata(self.german_relation)
        source.observed_metadata = {"resolution": "2160p"}
        source.last_observed_at = timezone.now()

        with (
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ) as mark_outdated,
            patch(
                "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
            ) as enqueue_all,
            self.captureOnCommitCallbacks(execute=True),
        ):
            source.save(
                update_fields=[
                    "observed_metadata",
                    "last_observed_at",
                    "updated_at",
                ]
            )

        mark_outdated.assert_called_once_with(
            trigger_reason="VOD source metadata changed",
            policy_ids=[],
        )
        enqueue_all.assert_not_called()

    def test_lazy_relation_detail_metadata_does_not_touch_profiles(self):
        self.german_relation.custom_properties = {
            **(self.german_relation.custom_properties or {}),
            "detailed_info": {"video": {"height": 2160}},
        }
        self.german_relation.last_advanced_refresh = timezone.now()
        self.german_relation._skip_vod_profile_invalidation = True

        with (
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ) as mark_outdated,
            patch(
                "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
            ) as enqueue_all,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.german_relation.save(
                update_fields=["custom_properties", "last_advanced_refresh"]
            )

        mark_outdated.assert_not_called()
        enqueue_all.assert_not_called()

    def test_provider_profile_batch_waits_until_all_refreshes_finished(self):
        from django.core.cache import cache

        self.account_a.status = M3UAccount.Status.PARSING
        self.account_a.save(update_fields=["status"])
        _remember_profile_rebuild_after_vod_refresh()

        with patch(
            "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
        ) as enqueue:
            self.assertFalse(
                _enqueue_deferred_profile_rebuild_after_vod_refreshes()
            )
            enqueue.assert_not_called()

            self.account_a.status = M3UAccount.Status.SUCCESS
            self.account_a.save(update_fields=["status"])
            enqueue.return_value = True
            self.assertTrue(
                _enqueue_deferred_profile_rebuild_after_vod_refreshes()
            )

        enqueue.assert_called_once_with(
            trigger_reason=(
                "One or more completed VOD provider refreshes changed the "
                "source catalog"
            )
        )
        self.assertIsNone(cache.get(VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY))

    def test_changed_provider_catalog_updates_profiles_and_queues_auto_tmdb(self):
        from django.core.cache import cache

        _remember_profile_rebuild_after_vod_refresh()
        with (
            patch.object(
                CoreSettings,
                "get_tmdb_auto_enrich",
                return_value=True,
            ),
            patch.object(
                CoreSettings,
                "get_tmdb_api_token",
                return_value="configured-token",
            ),
            patch(
                "apps.vod.tasks.enqueue_tmdb_enrichment",
                return_value={"queued": True, "status": "queued", "task_id": ""},
            ) as enqueue_tmdb,
            patch(
                "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
            ) as enqueue_profiles,
        ):
            enqueue_profiles.return_value = True
            self.assertTrue(
                _enqueue_deferred_profile_rebuild_after_vod_refreshes()
            )

        enqueue_tmdb.assert_called_once_with(
            rebuild_profiles=True,
            trigger_reason=(
                "A completed provider VOD refresh changed the catalog"
            ),
        )
        enqueue_profiles.assert_not_called()
        self.assertIsNone(cache.get(VOD_PROFILE_REBUILD_AFTER_REFRESH_KEY))

    def test_profile_preview_filters_prepared_rows(self):
        build_vod_profile_selection(self.policy.id)
        admin = get_user_model().objects.create_user(
            username="profile-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {
                "type": "movie",
                "audio_language": "deu",
                "resolution": "1080p",
            },
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["relation_id"],
            self.german_relation.id,
        )
        self.assertEqual(
            response.data["results"][0]["metadata"]["audio_languages"],
            ["ger"],
        )

    def test_profile_preview_filters_by_current_canonical_metadata_state(self):
        build_vod_profile_selection(self.policy.id)
        admin = get_user_model().objects.create_user(
            username="profile-metadata-preview-admin",
            password="test-password",
            user_level=10,
        )
        self.movie.tmdb_status = "matched"
        self.movie.save(update_fields=["tmdb_status", "updated_at"])
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {"type": "movie", "metadata_status": "missing_metadata"},
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)

    def test_profile_preview_filters_by_genre_anime_and_adult_flags(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.save(update_fields=["hard_constraints", "updated_at"])
        self.movie.tmdb_metadata = {
            "genres": [{"id": 878, "name": "Science Fiction"}],
            "is_anime": True,
            "adult": False,
        }
        self.movie.save(update_fields=["tmdb_metadata", "updated_at"])
        build_vod_profile_selection(self.policy.id)
        admin = get_user_model().objects.create_user(
            username="profile-canonical-filter-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {
                "type": "movie",
                "genre": "science fiction",
                "anime_mode": "yes",
                "adult_mode": "no",
            },
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)

    def test_compact_preview_reports_all_eligible_failover_sources(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.save(update_fields=["hard_constraints", "updated_at"])
        build_vod_profile_selection(self.policy.id)
        admin = get_user_model().objects.create_user(
            username="compact-source-count-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {"type": "movie"},
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["source_count"], 2)

    def test_preview_keeps_active_compact_shape_while_variants_builds(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.save(update_fields=["hard_constraints", "updated_at"])
        build_vod_profile_selection(self.policy.id)
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            export_mode=VODAccessPolicy.ExportMode.VARIANTS,
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
        )
        admin = get_user_model().objects.create_user(
            username="active-compact-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {"type": "movie"},
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["source_count"], 2)

    def test_compact_candidate_preview_uses_production_order_and_reasons(self):
        admin = get_user_model().objects.create_user(
            username="candidate-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/candidates/",
            {
                "type": "movie",
                "canonical_id": self.movie.id,
                "current_relation_id": self.english_relation.id,
            },
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "candidates"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["eligible_count"], 1)
        rows = response.data["results"]
        self.assertEqual(
            [row["relation_id"] for row in rows],
            [self.german_relation.id, self.english_relation.id],
        )
        self.assertTrue(rows[0]["allowed"])
        self.assertTrue(rows[0]["selected"])
        self.assertEqual(rows[0]["position"], 1)
        self.assertFalse(rows[1]["allowed"])
        self.assertTrue(rows[1]["current"])
        self.assertEqual(rows[1]["reason"], "language_not_matched")

    def test_policy_evaluation_explains_feature_exclusion(self):
        self.english_category.metadata_defaults = {
            **self.english_category.metadata_defaults,
            "video_features": ["3d"],
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        self.policy.hard_constraints = {
            "excluded_video_features": ["3d"],
        }

        result = relation_policy_evaluation(
            self.english_relation,
            self.policy,
        )

        self.assertEqual(
            result,
            {"allowed": False, "reason": "feature_excluded", "rule_id": ""},
        )

    def test_draft_stream_filter_preview_respects_order_and_category_scope(self):
        admin = get_user_model().objects.create_user(
            username="draft-filter-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().post(
            "/api/vod/access-policies/preview-stream-filter/",
            {
                "target_rule_id": "english-only",
                "category_relation_ids": [
                    self.german_category.id,
                    self.english_category.id,
                ],
                "source_rules": [
                    {
                        "id": "german-first",
                        "match_field": "category",
                        "regex_pattern": "GERMANY",
                        "result": "include",
                    },
                    {
                        "id": "english-only",
                        "match_field": "category",
                        "regex_pattern": "NETFLIX",
                        "required_audio_languages": ["eng"],
                        "result": "exclude",
                    },
                ],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view(
            {"post": "preview_stream_filter"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["id"], self.english_relation.id
        )
        self.assertEqual(response.data["results"][0]["result"], "exclude")
        self.assertEqual(
            response.data["results"][0]["provider_title"],
            "Avatar",
        )
        self.assertEqual(
            response.data["results"][0]["canonical_title"],
            "Avatar",
        )
        self.assertEqual(
            response.data["results"][0]["canonical_id"],
            self.movie.id,
        )
        self.assertEqual(
            response.data["results"][0]["relation_id"],
            self.english_relation.id,
        )

    def test_empty_category_expression_applies_feature_filter_globally(self):
        self.english_category.metadata_defaults = {
            **self.english_category.metadata_defaults,
            "video_features": ["3d"],
        }
        self.english_category.save(update_fields=["metadata_defaults"])
        admin = get_user_model().objects.create_user(
            username="global-feature-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().post(
            "/api/vod/access-policies/preview-stream-filter/",
            {
                "target_rule_id": "exclude-3d",
                "category_relation_ids": [],
                "source_rules": [
                    {
                        "id": "exclude-3d",
                        "match_field": "category",
                        "regex_pattern": "",
                        "required_video_features": ["3d"],
                        "result": "exclude",
                    }
                ],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view(
            {"post": "preview_stream_filter"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(
            response.data["results"][0]["id"], self.english_relation.id
        )

    def test_draft_filter_preview_can_explicitly_restrict_to_no_categories(self):
        admin = get_user_model().objects.create_user(
            username="empty-draft-filter-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().post(
            "/api/vod/access-policies/preview-stream-filter/",
            {
                "target_rule_id": "english-only",
                "category_relation_ids": [],
                "restrict_to_categories": True,
                "source_rules": [
                    {
                        "id": "english-only",
                        "required_audio_languages": ["eng"],
                        "result": "include",
                    }
                ],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view(
            {"post": "preview_stream_filter"}
        )(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["inventory_count"], 0)
        self.assertEqual(response.data["count"], 0)

    def test_pending_profile_previews_and_serves_last_completed_generation(self):
        build_vod_profile_selection(self.policy.id)
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            selection_progress={"phase": "Waiting for worker", "percent": 0},
        )
        self.policy.refresh_from_db()

        self.assertEqual(
            prepared_relation_ids(
                self.policy,
                M3UMovieRelation,
                {"m3u_account__is_active": True},
            ),
            [self.german_relation.id],
        )

        admin = get_user_model().objects.create_user(
            username="stale-profile-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {"type": "movie"},
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["current"])
        self.assertTrue(response.data["available"])
        self.assertEqual(response.data["count"], 1)

    def test_variants_preview_uses_each_provider_source_name(self):
        self.german_relation.custom_properties = {
            "basic_data": {"name": "| DE | Avatar source"}
        }
        self.german_relation.save(update_fields=["custom_properties", "updated_at"])
        self.english_relation.custom_properties = {
            "basic_data": {"name": "| EN | Avatar source"}
        }
        self.english_relation.save(update_fields=["custom_properties", "updated_at"])
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.naming_mode = VODAccessPolicy.NamingMode.MODE_DEFAULT
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.save(
            update_fields=[
                "export_mode",
                "naming_mode",
                "hard_constraints",
                "updated_at",
            ]
        )
        build_vod_profile_selection(self.policy.id)

        admin = get_user_model().objects.create_user(
            username="variants-preview-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/access-policies/{self.policy.id}/selections/",
            {"type": "movie"},
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"get": "selections"})(
            request,
            pk=self.policy.id,
        )

        self.assertEqual(response.status_code, 200, response.data)
        rows = {row["relation_id"]: row for row in response.data["results"]}
        self.assertEqual(
            rows[self.german_relation.id]["name"], "| DE | Avatar source"
        )
        self.assertEqual(
            rows[self.english_relation.id]["name"], "| EN | Avatar source"
        )
        self.assertEqual(
            rows[self.german_relation.id]["category_name"], self.german.name
        )
        self.assertEqual(
            rows[self.english_relation.id]["category_name"], self.english.name
        )

    def test_switching_profile_to_variants_queues_catalog_update(self):
        admin = get_user_model().objects.create_user(
            username="variants-update-admin",
            password="test-password",
            user_level=10,
        )
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.READY,
            selection_progress={"phase": "Ready", "percent": 100},
        )
        request = APIRequestFactory().patch(
            f"/api/vod/access-policies/{self.policy.pk}/",
            {"export_mode": VODAccessPolicy.ExportMode.VARIANTS},
            format="json",
        )
        force_authenticate(request, user=admin)

        with (
            patch(
                "apps.vod.tasks.rebuild_vod_profile_selection.delay"
            ) as delay,
            patch(
                "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
            ) as enqueue_all,
            patch(
                "apps.vod.profile_selection.transaction.on_commit",
                side_effect=lambda callback: callback(),
            ),
        ):
            delay.return_value.id = "variants-update-task"
            response = VODAccessPolicyViewSet.as_view(
                {"patch": "partial_update"}
            )(request, pk=self.policy.pk)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["export_mode"], VODAccessPolicy.ExportMode.VARIANTS
        )
        self.assertEqual(
            response.data["selection_status"],
            VODAccessPolicy.SelectionStatus.PENDING,
        )
        self.assertEqual(
            response.data["selection_progress"]["task_id"],
            "variants-update-task",
        )
        self.assertEqual(
            response.data["selection_progress"]["task_name"],
            "apps.vod.tasks.rebuild_vod_profile_selection",
        )
        self.assertIn("active_selection_generation", response.data)
        self.assertIn("selection_catalog_generation", response.data)
        delay.assert_called_once_with(self.policy.pk)
        enqueue_all.assert_not_called()

    def test_outdated_profile_can_be_rebuilt_manually(self):
        admin = get_user_model().objects.create_user(
            username="profile-rebuild-admin",
            password="test-password",
            user_level=10,
        )
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.OUTDATED,
            active_selection_generation="last-ready-catalog",
            selection_progress={
                "phase": "Catalog rebuild required",
                "percent": 0,
            },
        )
        request = APIRequestFactory().post(
            f"/api/vod/access-policies/{self.policy.pk}/rebuild/",
            {},
            format="json",
        )
        force_authenticate(request, user=admin)

        with (
            patch("apps.vod.tasks.rebuild_vod_profile_selection.delay") as delay,
            patch(
                "apps.vod.profile_selection.transaction.on_commit",
                side_effect=lambda callback: callback(),
            ),
        ):
            delay.return_value.id = "manual-profile-rebuild"
            response = VODAccessPolicyViewSet.as_view({"post": "rebuild"})(
                request,
                pk=self.policy.pk,
            )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["selection_status"],
            VODAccessPolicy.SelectionStatus.PENDING,
        )
        self.assertEqual(
            response.data["selection_progress"]["task_id"],
            "manual-profile-rebuild",
        )
        delay.assert_called_once_with(self.policy.pk)

    def test_deleting_default_profile_promotes_an_active_replacement(self):
        admin = get_user_model().objects.create_user(
            username="profile-delete-admin",
            password="test-password",
            user_level=10,
        )
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_default=False,
            is_active=False,
        )
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            is_default=True,
            is_active=True,
        )
        replacement = VODAccessPolicy.objects.create(
            name="Active replacement",
            is_active=True,
            is_default=False,
        )
        request = APIRequestFactory().delete(
            f"/api/vod/access-policies/{self.policy.pk}/"
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"delete": "destroy"})(
            request,
            pk=self.policy.pk,
        )

        self.assertEqual(response.status_code, 204, response.data)
        self.assertFalse(VODAccessPolicy.objects.filter(pk=self.policy.pk).exists())
        replacement.refresh_from_db()
        self.assertTrue(replacement.is_default)

    def test_last_active_default_profile_cannot_be_deleted(self):
        admin = get_user_model().objects.create_user(
            username="last-profile-delete-admin",
            password="test-password",
            user_level=10,
        )
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_default=False,
            is_active=False,
        )
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            is_default=True,
            is_active=True,
        )
        request = APIRequestFactory().delete(
            f"/api/vod/access-policies/{self.policy.pk}/"
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"delete": "destroy"})(
            request,
            pk=self.policy.pk,
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(VODAccessPolicy.objects.filter(pk=self.policy.pk).exists())

    def test_global_rebuild_schedules_a_followup_for_late_invalidation(self):
        second_policy = VODAccessPolicy.objects.create(
            name="Second profile",
            export_mode=VODAccessPolicy.ExportMode.COMPACT,
            is_active=True,
            hard_constraints={"allow_unknown_metadata": True},
        )
        VODAccessPolicy.objects.exclude(
            pk__in=[self.policy.pk, second_policy.pk]
        ).update(is_active=False)
        VODAccessPolicy.objects.filter(
            pk__in=[self.policy.pk, second_policy.pk]
        ).update(selection_status=VODAccessPolicy.SelectionStatus.PENDING)
        built = []

        def complete_build(policy_id, **_kwargs):
            VODAccessPolicy.objects.filter(pk=policy_id).update(
                selection_status=VODAccessPolicy.SelectionStatus.READY
            )
            built.append(policy_id)
            if len(built) == 2:
                VODAccessPolicy.objects.filter(pk=built[0]).update(
                    selection_status=VODAccessPolicy.SelectionStatus.PENDING
                )
            return {}

        with (
            patch(
                "apps.vod.profile_selection.build_vod_profile_selection",
                side_effect=complete_build,
            ),
            patch.object(
                rebuild_all_vod_profile_selections,
                "apply_async",
            ) as apply_async,
        ):
            apply_async.return_value.id = "followup-task-id"
            rebuild_all_vod_profile_selections.run()

        self.assertEqual(len(built), 2)
        apply_async.assert_called_once_with(countdown=1)
        first_policy = VODAccessPolicy.objects.get(pk=built[0])
        self.assertEqual(
            first_policy.selection_progress["task_id"], "followup-task-id"
        )
        self.assertEqual(
            first_policy.selection_progress["task_name"],
            "apps.vod.tasks.rebuild_all_vod_profile_selections",
        )
        self.assertTrue(first_policy.selection_progress["batch"])

    def test_catalog_invalidation_republishes_an_existing_pending_profile(self):
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_active=False
        )
        started_at = timezone.now() - timedelta(minutes=2)
        progress = {
            "phase": "Waiting in Celery queue",
            "percent": 0,
            "task_id": "existing-task-id",
        }
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            selection_started_at=started_at,
            selection_progress=progress,
        )

        with (
            patch("django.core.cache.cache.add", return_value=True),
            patch(
                "apps.vod.tasks.rebuild_all_vod_profile_selections.delay"
            ) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            delay.return_value.id = "replacement-task-id"
            queued = enqueue_all_profile_selection_rebuilds()

        self.policy.refresh_from_db()
        self.assertTrue(queued)
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.PENDING,
        )
        self.assertEqual(self.policy.selection_started_at, started_at)
        self.assertEqual(
            self.policy.selection_progress["task_id"], "replacement-task-id"
        )
        self.assertEqual(
            self.policy.selection_progress["task_name"],
            "apps.vod.tasks.rebuild_all_vod_profile_selections",
        )
        self.assertEqual(
            self.policy.selection_progress["trigger_reason"],
            "The VOD source catalog or source metadata changed",
        )
        self.assertEqual(self.policy.selection_progress["batch_position"], 1)
        self.assertEqual(self.policy.selection_progress["batch_total"], 1)
        delay.assert_called_once_with()

    def test_watchdog_republishes_pending_profile_with_completed_task(self):
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(is_active=False)
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            selection_started_at=timezone.now() - timedelta(minutes=5),
            selection_progress={
                "phase": "Waiting in Celery queue",
                "percent": 0,
                "task_id": "completed-task-id",
            },
        )

        with (
            patch("celery.result.AsyncResult") as async_result,
            patch("django.core.cache.cache.get", return_value="completed-task-id"),
            patch("django.core.cache.cache.delete"),
            patch("django.core.cache.cache.add", return_value=True),
            patch("django.core.cache.cache.set"),
            patch(
                "apps.vod.tasks.rebuild_all_vod_profile_selections.delay"
            ) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            async_result.return_value.state = "SUCCESS"
            delay.return_value.id = "replacement-task-id"
            result = reconcile_vod_profile_selection_queue.run()

        self.policy.refresh_from_db()
        self.assertEqual(result["stranded_pending"], [self.policy.pk])
        self.assertTrue(result["republished"])
        self.assertEqual(
            self.policy.selection_progress["task_id"], "replacement-task-id"
        )
        delay.assert_called_once_with()

    def test_watchdog_recovers_a_build_without_a_recent_progress_heartbeat(self):
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(is_active=False)
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            selection_started_at=timezone.now() - timedelta(hours=2),
            selection_progress={
                "phase": "Selecting movies sources",
                "percent": 6,
                "task_id": "interrupted-task-id",
                "build_generation": "interrupted-generation",
                "updated_at": (
                    timezone.now() - timedelta(hours=1)
                ).isoformat(),
            },
        )

        with (
            patch(
                "django.core.cache.cache.get",
                return_value="interrupted-task-id",
            ),
            patch("django.core.cache.cache.delete"),
            patch("django.core.cache.cache.add", return_value=True),
            patch("django.core.cache.cache.set"),
            patch(
                "apps.vod.tasks.rebuild_all_vod_profile_selections.delay"
            ) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            delay.return_value.id = "recovery-task-id"
            result = reconcile_vod_profile_selection_queue.run()

        self.policy.refresh_from_db()
        self.assertEqual(result["stalled_building"], [self.policy.pk])
        self.assertTrue(result["republished"])
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.PENDING,
        )
        self.assertEqual(
            self.policy.selection_progress["task_id"], "recovery-task-id"
        )
        self.assertEqual(
            self.policy.selection_progress["trigger_reason"],
            "Automatic recovery: the previous VOD profile build stopped "
            "reporting progress",
        )
        self.assertEqual(
            self.policy.selection_progress["task_name"],
            "apps.vod.tasks.rebuild_all_vod_profile_selections",
        )
        delay.assert_called_once_with()

    def test_watchdog_recovers_a_batch_task_lost_with_runtime_redis(self):
        VODAccessPolicy.objects.exclude(pk=self.policy.pk).update(
            is_active=False
        )
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.PENDING,
            selection_started_at=timezone.now() - timedelta(minutes=5),
            selection_progress={
                "phase": "Waiting in Celery queue",
                "percent": 0,
                "task_id": "task-lost-on-restart",
                "task_name": (
                    "apps.vod.tasks.rebuild_all_vod_profile_selections"
                ),
                "batch": True,
                "trigger_reason": "A source metadata field changed",
            },
        )

        with (
            patch("celery.result.AsyncResult") as async_result,
            patch("django.core.cache.cache.get", return_value=None),
            patch("django.core.cache.cache.delete"),
            patch("django.core.cache.cache.add", return_value=True),
            patch("django.core.cache.cache.set"),
            patch(
                "apps.vod.tasks.rebuild_all_vod_profile_selections.delay"
            ) as delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            async_result.return_value.state = "PENDING"
            delay.return_value.id = "recovered-task-id"
            result = reconcile_vod_profile_selection_queue.run()

        self.policy.refresh_from_db()
        self.assertEqual(result["stranded_pending"], [self.policy.pk])
        self.assertTrue(result["republished"])
        self.assertEqual(
            self.policy.selection_progress["task_id"], "recovered-task-id"
        )
        self.assertEqual(
            self.policy.selection_progress["trigger_reason"],
            "Automatic recovery: the previous Celery task is no longer "
            "available after a service restart",
        )
        self.assertEqual(
            self.policy.selection_progress["original_trigger_reason"],
            "A source metadata field changed",
        )
        delay.assert_called_once_with()

    def test_building_profile_uses_database_heartbeat_as_running_state(self):
        VODAccessPolicy.objects.filter(pk=self.policy.pk).update(
            selection_status=VODAccessPolicy.SelectionStatus.BUILDING,
            selection_progress={
                "phase": "Selecting movies sources",
                "processed": 5000,
                "total": 80000,
                "task_id": "backend-forgot-this-task",
                "updated_at": timezone.now().isoformat(),
            },
        )
        self.policy.refresh_from_db()

        with patch("celery.result.AsyncResult") as async_result:
            serialized = VODAccessPolicySerializer(self.policy).data

        self.assertEqual(serialized["selection_task_state"], "RUNNING")
        async_result.assert_not_called()

    def test_admin_can_create_a_reusable_vod_output_profile(self):
        admin = get_user_model().objects.create_user(
            username="profile-create-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().post(
            "/api/vod/access-policies/",
            {
                "name": "German 1080p",
                "export_mode": "compact",
                "is_active": True,
                "is_default": False,
                "hard_constraints": {
                    "required_audio_languages": ["deu"],
                    "required_subtitle_languages": ["ger"],
                    "language_match_mode": "any",
                    "min_resolution": 720,
                    "max_resolution": 1080,
                    "allow_unknown_metadata": False,
                },
                "ranking": [
                    "audio_language",
                    "subtitle_language",
                    "provider",
                    "resolution",
                ],
                "provider_order": [
                    self.account_b.id,
                    self.account_a.id,
                    self.account_b.id,
                ],
                "category_rules": [
                    {
                        "category_relation": self.german_category.id,
                        "enabled": True,
                        "priority": 0,
                    }
                ],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"post": "create"})(request)

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(
            response.data["selection_status"],
            VODAccessPolicy.SelectionStatus.PENDING,
        )
        self.assertEqual(
            response.data["selection_progress"]["phase"],
            "Publishing background task",
        )
        created = VODAccessPolicy.objects.get(name="German 1080p")
        self.assertEqual(
            created.hard_constraints["required_audio_languages"], ["ger"]
        )
        self.assertEqual(
            created.ranking,
            [
                "audio_language",
                "subtitle_language",
                "provider",
                "resolution_desc",
            ],
        )
        self.assertEqual(
            created.provider_order,
            [self.account_b.id, self.account_a.id],
        )
        self.assertEqual(
            list(
                created.vodpolicycategory_set.values_list(
                    "category_relation_id", flat=True
                )
            ),
            [self.german_category.id],
        )

    def test_profile_rejects_conflicting_resolution_ranking_directions(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Conflicting resolution directions",
                "ranking": ["resolution_desc", "resolution_asc"],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("ranking", serializer.errors)

    def test_profile_rejects_bitrate_ranking(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Unsupported bitrate ranking",
                "ranking": ["bitrate_desc"],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("ranking", serializer.errors)

    def test_profile_rejects_invalid_provider_order(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Invalid provider order",
                "provider_order": [self.account_a.id, "not-an-account"],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("provider_order", serializer.errors)

    def test_profile_rejects_invalid_source_rule_expression(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Invalid category rule",
                "hard_constraints": {
                    "source_rules": [
                        {
                            "name": "Broken",
                            "category_regex": "[",
                        }
                    ]
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("hard_constraints", serializer.errors)

    def test_profile_rejects_duplicate_stream_filters(self):
        rule = {
            "match_field": "category",
            "regex_pattern": "ANIME",
            "required_subtitle_languages": ["ger"],
            "result": "include",
        }
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Duplicate filters",
                "hard_constraints": {"source_rules": [rule, rule]},
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("hard_constraints", serializer.errors)

    def test_profile_normalizes_metadata_content_filters_and_default_action(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "English family content",
                "hard_constraints": {
                    "content_default_action": "exclude",
                    "source_rules": [
                        {
                            "id": "english-family",
                            "match_field": "stream",
                            "regex_pattern": "",
                            "required_audio_languages": ["en"],
                            "required_genres": [" Family ", "family"],
                            "required_keywords": ["animation"],
                            "adult_mode": "no",
                            "tmdb_mode": "missing",
                            "max_year": 2030,
                            "min_rating": 5.5,
                            "result": "include",
                        }
                    ],
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        constraints = serializer.validated_data["hard_constraints"]
        self.assertEqual(constraints["content_default_action"], "exclude")
        rule = constraints["source_rules"][0]
        self.assertEqual(rule["required_audio_languages"], ["eng"])
        self.assertEqual(rule["required_genres"], ["Family"])
        self.assertEqual(rule["required_keywords"], ["animation"])
        self.assertEqual(rule["adult_mode"], "no")
        self.assertEqual(rule["tmdb_mode"], "missing")
        self.assertEqual(rule["min_rating"], 5.5)

    def test_profile_rejects_external_ids_in_content_filters(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "One title disguised as a reusable rule",
                "hard_constraints": {
                    "source_rules": [
                        {
                            "match_field": "stream",
                            "regex_pattern": "",
                            "tmdb_ids": ["19995"],
                            "result": "exclude",
                        }
                    ]
                },
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("hard_constraints", serializer.errors)

    def test_profile_rejects_duplicate_edition_matches(self):
        rule = {
            "match_field": "any",
            "min_resolution": 2160,
            "required_video_features": ["hdr"],
        }
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Duplicate editions",
                "edition_rules": [
                    {**rule, "id": "uhd-a", "name": "UHD A"},
                    {**rule, "id": "uhd-b", "name": "UHD B"},
                ],
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("edition_rules", serializer.errors)

    def test_profile_editions_use_suffix_and_metadata_conditions_only(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Simple editions",
                "edition_rules": [
                    {
                        "id": "uhd",
                        "title_suffix": "4K",
                        "match_field": "stream",
                        "regex_pattern": "legacy expression",
                        "case_sensitive": True,
                        "min_resolution": 2160,
                    }
                ],
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["edition_rules"],
            [
                {
                    "id": "uhd",
                    "name": "4K",
                    "title_suffix": "4K",
                    "enabled": True,
                    "min_resolution": 2160,
                    "max_resolution": 0,
                    "required_audio_languages": [],
                    "required_subtitle_languages": [],
                    "required_video_features": [],
                }
            ],
        )

    def test_profile_rejects_unknown_title_template_placeholders(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Invalid title template",
                "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
                "name_template": "{title} {unknown_value}",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("name_template", serializer.errors)

    def test_compact_template_rejects_source_specific_fields(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Unsafe Compact naming",
                "export_mode": VODAccessPolicy.ExportMode.COMPACT,
                "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
                "name_template": "{title} {provider}",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("name_template", serializer.errors)

    def test_profile_template_requires_title_placeholder(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Missing title field",
                "export_mode": VODAccessPolicy.ExportMode.VARIANTS,
                "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
                "name_template": "{provider} {resolution}",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("name_template", serializer.errors)

    def test_compact_template_accepts_canonical_title_year_and_edition(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Localized compact output",
                "export_mode": VODAccessPolicy.ExportMode.COMPACT,
                "metadata_source": VODAccessPolicy.MetadataSource.PROVIDER,
                "canonical_title_source": (
                    VODAccessPolicy.CanonicalTitleSource.SECONDARY
                ),
                "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
                "name_template": "{title} ({year}) {edition}",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_compact_template_rejects_provider_title_source(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Invalid provider compact output",
                "export_mode": VODAccessPolicy.ExportMode.COMPACT,
                "canonical_title_source": (
                    VODAccessPolicy.CanonicalTitleSource.PROVIDER
                ),
                "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
                "name_template": "{title} ({year}) {edition}",
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("canonical_title_source", serializer.errors)

    def test_variants_template_accepts_provider_fields_and_features(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Detailed source variants",
                "export_mode": VODAccessPolicy.ExportMode.VARIANTS,
                "canonical_title_source": (
                    VODAccessPolicy.CanonicalTitleSource.PROVIDER
                ),
                "naming_mode": VODAccessPolicy.NamingMode.TEMPLATE,
                "name_template": (
                    "{title} {provider} {dub} {sub} {resolution} "
                    "{format} {features}"
                ),
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_variants_created_without_format_receive_safe_defaults(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Default source variants",
                "export_mode": VODAccessPolicy.ExportMode.VARIANTS,
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["naming_mode"],
            VODAccessPolicy.NamingMode.TEMPLATE,
        )
        self.assertEqual(serializer.validated_data["name_template"], "{title}")

    @patch.object(
        CoreSettings,
        "get_tmdb_languages",
        return_value=["de-DE", "en-US"],
    )
    def test_missing_secondary_title_falls_back_to_provider_title(self, _languages):
        self.movie.display_name = "Avatar Deutsch"
        self.movie.tmdb_metadata = {
            "localized": {"de-DE": {"title": "Avatar Deutsch"}}
        }
        self.movie.save(update_fields=["display_name", "tmdb_metadata"])
        self.german_relation.custom_properties = {
            "movie_data": {"name": "Provider Avatar UHD"}
        }
        self.german_relation.save(update_fields=["custom_properties"])
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.naming_mode = VODAccessPolicy.NamingMode.TEMPLATE
        self.policy.name_template = "{title} [{resolution}]"
        self.policy.canonical_title_source = (
            VODAccessPolicy.CanonicalTitleSource.SECONDARY
        )

        output_name = policy_output_name(
            self.movie,
            self.german_relation,
            self.policy,
            metadata={"resolution": "2160p"},
        )

        self.assertEqual(output_name, "Provider Avatar UHD [2160p]")

    def test_provider_title_and_features_fill_generic_variant_template(self):
        self.german_relation.custom_properties = {
            "movie_data": {"name": "Provider Avatar UHD"}
        }
        self.german_relation.save(update_fields=["custom_properties"])
        self.policy.export_mode = VODAccessPolicy.ExportMode.VARIANTS
        self.policy.naming_mode = VODAccessPolicy.NamingMode.TEMPLATE
        self.policy.name_template = "{title} [{features}]"
        self.policy.canonical_title_source = (
            VODAccessPolicy.CanonicalTitleSource.PROVIDER
        )

        output_name = policy_output_name(
            self.movie,
            self.german_relation,
            self.policy,
            metadata={"video_features": ["hdr10", "dolby_vision"]},
        )

        self.assertEqual(
            output_name,
            "Provider Avatar UHD [HDR10+DOLBY_VISION]",
        )

    def test_profile_keeps_simplified_stream_filter_payload_compact(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Stream filters only",
                "hard_constraints": {
                    "source_rules": [
                        {
                            "match_field": "category",
                            "regex_pattern": "ANIME",
                            "required_subtitle_languages": ["deu"],
                            "result": "include",
                        }
                    ]
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        constraints = serializer.validated_data["hard_constraints"]
        self.assertEqual(set(constraints), {"source_rules"})
        self.assertEqual(
            constraints["source_rules"][0]["required_subtitle_languages"],
            ["ger"],
        )

    def test_profile_validates_dynamic_category_import_configuration(self):
        serializer = VODAccessPolicySerializer(
            data={
                "name": "Dynamic Hindi catalog",
                "hard_constraints": {
                    "source_rules": [],
                    "category_import_rules": [
                        {
                            "id": "hindi-provider-a",
                            "scope": "movie",
                            "m3u_account_id": str(self.account_a.id),
                            "match_field": "group_name",
                            "regex_pattern": "hindi|bollywood",
                            "action": "enable",
                        }
                    ],
                },
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        constraints = serializer.validated_data["hard_constraints"]
        self.assertEqual(
            set(constraints),
            {
                "source_rules",
                "category_import_rules",
            },
        )
        self.assertEqual(
            constraints["category_import_rules"][0]["m3u_account_id"],
            self.account_a.id,
        )
        self.assertNotIn("category_default_actions", constraints)

    def test_admin_can_replace_vod_output_profile_categories(self):
        admin = get_user_model().objects.create_user(
            username="profile-update-admin",
            password="test-password",
            user_level=10,
        )
        VODPolicyCategory.objects.create(
            policy=self.policy,
            category_relation=self.german_category,
            enabled=True,
        )
        request = APIRequestFactory().patch(
            f"/api/vod/access-policies/{self.policy.pk}/",
            {
                "category_rules": [
                    {
                        "category_relation": self.english_category.id,
                        "enabled": True,
                        "priority": 0,
                    }
                ]
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODAccessPolicyViewSet.as_view({"patch": "partial_update"})(
            request,
            pk=self.policy.pk,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["selection_status"],
            VODAccessPolicy.SelectionStatus.PENDING,
        )
        self.assertEqual(
            [rule["category_relation"] for rule in response.data["category_rules"]],
            [self.english_category.id],
        )
        self.assertEqual(
            list(
                self.policy.vodpolicycategory_set.values_list(
                    "category_relation_id", flat=True
                )
            ),
            [self.english_category.id],
        )

    def test_compact_xc_category_requests_do_not_duplicate_the_title(self):
        self.policy.hard_constraints = {"allow_unknown_metadata": True}
        self.policy.save(update_fields=["hard_constraints", "updated_at"])
        user = get_user_model().objects.create_user(
            username="compact-user",
            password="test-password",
        )
        self.policy.users.add(user)
        request = RequestFactory().get("/player_api.php")

        all_rows = xc_get_vod_streams(request, user)
        german_rows = xc_get_vod_streams(
            request,
            user,
            category_id=self.german.id,
        )
        english_rows = xc_get_vod_streams(
            request,
            user,
            category_id=self.english.id,
        )

        self.assertEqual(
            [row["stream_id"] for row in all_rows],
            [self.english_relation.id],
        )
        self.assertEqual(german_rows, [])
        self.assertEqual(
            [row["stream_id"] for row in english_rows],
            [self.english_relation.id],
        )

    def test_xc_categories_follow_global_enabled_categories_not_old_priorities(self):
        user = get_user_model().objects.create_user(
            username="category-user",
            password="test-password",
        )
        self.policy.users.add(user)

        rows = xc_get_vod_categories(user)

        self.assertEqual(
            {row["category_id"] for row in rows},
            {str(self.german.id), str(self.english.id)},
        )

    def test_xc_categories_follow_the_user_category_allowlist(self):
        user = get_user_model().objects.create_user(
            username="limited-category-user",
            password="test-password",
        )
        self.policy.users.add(user)
        VODPolicyCategory.objects.create(
            policy=self.policy,
            category_relation=self.german_category,
            enabled=True,
        )

        rows = xc_get_vod_categories(user)

        self.assertEqual(
            [row["category_id"] for row in rows],
            [str(self.german.id)],
        )

    def test_same_provider_id_is_not_automatically_linked_across_accounts(self):
        first = initialize_relation_metadata(self.german_relation)
        second = initialize_relation_metadata(self.english_relation)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual(first.stream_id, second.stream_id)
        self.assertNotEqual(first.m3u_account_id, second.m3u_account_id)

    def test_bulk_metadata_initialization_keeps_relations_distinct(self):
        source_keys = initialize_relations_metadata(
            [self.german_relation, self.english_relation]
        )
        self.german_relation.refresh_from_db()
        self.english_relation.refresh_from_db()

        self.assertEqual(
            source_keys,
            {
                ("movie", self.german_relation.id),
                ("movie", self.english_relation.id),
            },
        )

    def test_manual_metadata_wins_and_is_not_overwritten(self):
        relation = self.german_relation
        M3UMovieRelation.objects.filter(pk=relation.pk).update(
            observed_metadata={"audio_languages": ["eng"], "resolution": "720p"},
            manual_metadata={"audio_languages": ["deu"]},
            locked_fields=["audio_languages"],
        )
        relation.refresh_from_db()

        relation.apply_observation({
            "audio_languages": ["fra"],
            "resolution": "1080p",
        })
        relation.refresh_from_db()

        self.assertEqual(relation.observed_metadata["audio_languages"], ["eng"])
        self.assertEqual(relation.observed_metadata["resolution"], "1080p")
        self.assertEqual(
            relation.effective_metadata()["values"]["audio_languages"],
            ["ger"],
        )

    def test_playback_history_keeps_the_exact_account_and_category(self):
        playback = record_playback_selection(
            session_id="redirect-test-1",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.REDIRECT,
            status=VODPlaybackSession.Status.REDIRECTED,
            failover_chain=[
                {"relation_id": self.german_relation.id, "result": "selected"}
            ],
        )

        self.german_relation.refresh_from_db()
        self.assertEqual(playback.m3u_account_id, self.account_a.id)
        self.assertEqual(playback.category_id, self.german.id)
        self.assertEqual(playback.relation_id, self.german_relation.id)
        self.assertEqual(playback.status, VODPlaybackSession.Status.REDIRECTED)
        self.assertEqual(playback.failover_count, 0)
        self.assertEqual(playback.bytes_sent, 0)
        self.assertEqual(
            self.german_relation.declared_metadata["audio_languages"],
            ["ger"],
        )

    def test_playback_history_follows_a_source_moved_to_another_movie(self):
        playback = record_playback_selection(
            session_id="history-moved-movie",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        replacement = Movie.objects.create(name="Replacement Movie")
        self.german_relation.movie = replacement
        self.german_relation.save(update_fields=["movie"])

        data = VODPlaybackSessionSerializer(playback).data

        self.assertEqual(data["detail_content_type"], "movie")
        self.assertEqual(data["detail_canonical_id"], replacement.id)
        self.assertEqual(data["detail_relation_id"], self.german_relation.id)

    def test_playback_history_counts_rejected_failover_attempts(self):
        playback = record_playback_selection(
            session_id="redirect-test-failover",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.REDIRECT,
            status=VODPlaybackSession.Status.REDIRECTED,
            failover_chain=[
                {"relation_id": self.english_relation.id, "result": "upstream_error"},
                {"relation_id": self.german_relation.id, "result": "selected"},
            ],
        )

        self.assertEqual(playback.failover_count, 1)

    def test_range_reconnect_clears_stale_playback_end_time(self):
        record_playback_selection(
            session_id="proxy-range-reconnect",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.PROXYING,
        )
        playback = record_playback_selection(
            session_id="proxy-range-reconnect",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        self.assertIsNotNone(playback.ended_at)

        playback = record_playback_selection(
            session_id="proxy-range-reconnect",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.PROXYING,
        )

        self.assertEqual(playback.status, VODPlaybackSession.Status.PROXYING)
        self.assertIsNone(playback.ended_at)

    def test_playback_history_exposes_the_recorded_technical_snapshot(self):
        playback = record_playback_selection(
            session_id="proxy-test-1",
            user=None,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.PROXYING,
            custom_properties={
                "source_effective_metadata": {
                    "audio_languages": ["deu"],
                    "resolution": "1080p",
                }
            },
        )

        metadata = VODPlaybackSessionSerializer(playback).data[
            "source_effective_metadata"
        ]
        self.assertEqual(metadata["values"]["audio_languages"], ["ger"])
        self.assertEqual(metadata["values"]["resolution"], "1080p")
        self.assertEqual(metadata["provenance"]["resolution"], "playback")

    def test_episode_history_keeps_only_the_played_episode_title(self):
        provider_title = "| DE | Mushoku Tensei - S03E09 - 058 - Lament"
        canonical_title = (
            "NF - Mushoku Tensei (2021) - S03E09 - " + provider_title
        )

        self.assertEqual(
            episode_history_name(canonical_title),
            provider_title,
        )
        legacy = VODPlaybackSession(
            content_type="episode",
            content_name=canonical_title,
            custom_properties={},
        )
        self.assertEqual(
            VODPlaybackSessionSerializer(legacy).data["content_name"],
            provider_title,
        )

    def test_episode_history_points_to_its_parent_series_detail(self):
        series = Series.objects.create(name="History Series")
        category = VODCategory.objects.create(
            name="HISTORY SERIES", category_type="series"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_a,
            category=category,
            enabled=True,
        )
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=category,
            external_series_id="history-series",
        )
        episode = Episode.objects.create(
            series=series,
            name="Pilot",
            season_number=1,
            episode_number=1,
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="history-series-s01e01",
        )
        playback = record_playback_selection(
            session_id="history-series-episode",
            user=None,
            relation=episode_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )

        data = VODPlaybackSessionSerializer(playback).data

        self.assertEqual(data["detail_content_type"], "series")
        self.assertEqual(data["detail_canonical_id"], series.id)
        self.assertEqual(data["detail_relation_id"], series_relation.id)

    def test_series_history_filter_includes_series_episodes(self):
        admin = get_user_model().objects.create_user(
            username="history-series-admin",
            password="test-password",
            user_level=10,
        )
        VODPlaybackSession.objects.create(
            session_id="history-series-row",
            content_type="series",
            content_name="Series",
            mode=VODPlaybackSession.Mode.PROXY,
        )
        VODPlaybackSession.objects.create(
            session_id="history-episode-row",
            content_type="episode",
            content_name="Episode",
            mode=VODPlaybackSession.Mode.PROXY,
        )
        VODPlaybackSession.objects.create(
            session_id="history-movie-row",
            content_type="movie",
            content_name="Movie",
            mode=VODPlaybackSession.Mode.PROXY,
        )
        request = APIRequestFactory().get(
            "/api/vod/playback-sessions/", {"content_type": "series"}
        )
        force_authenticate(request, user=admin)

        response = VODPlaybackSessionViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(
            {row["content_type"] for row in response.data["results"]},
            {"series", "episode"},
        )

    def test_playback_history_filters_by_user_title_and_time_on_the_server(self):
        admin = get_user_model().objects.create_user(
            username="history-admin",
            password="test-password",
            user_level=10,
        )
        maria = get_user_model().objects.create_user(
            username="Maria",
            password="test-password",
        )
        playback = record_playback_selection(
            session_id="history-filter-match",
            user=maria,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        old = record_playback_selection(
            session_id="history-filter-old",
            user=maria,
            relation=self.english_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        VODPlaybackSession.objects.filter(pk=old.pk).update(
            started_at=timezone.now() - timedelta(days=10)
        )
        request = APIRequestFactory().get(
            "/api/vod/playback-sessions/",
            {
                "username": "mari",
                "search": "Avatar",
                "status": "completed",
                "started_after": (
                    timezone.now() - timedelta(days=1)
                ).isoformat(),
            },
        )
        force_authenticate(request, user=admin)

        response = VODPlaybackSessionViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], playback.id)

        account_search = APIRequestFactory().get(
            "/api/vod/playback-sessions/",
            {"search": self.account_a.name},
        )
        force_authenticate(account_search, user=admin)
        account_response = VODPlaybackSessionViewSet.as_view({"get": "list"})(
            account_search
        )
        self.assertEqual(account_response.data["count"], 0)

    def test_playback_history_facets_and_stats_use_stable_string_ids(self):
        admin = get_user_model().objects.create_user(
            username="history-facets-admin",
            password="test-password",
            user_level=10,
        )
        playback = record_playback_selection(
            session_id="history-facets-match",
            user=admin,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
            failover_chain=[
                {
                    "relation_id": self.english_relation.id,
                    "result": "at_capacity",
                },
                {"relation_id": self.german_relation.id, "result": "selected"},
            ],
        )
        VODPlaybackSession.objects.filter(pk=playback.pk).update(
            bytes_sent=1048576,
            watched_seconds=90,
        )

        facets_request = APIRequestFactory().get(
            "/api/vod/playback-sessions/facets/"
        )
        force_authenticate(facets_request, user=admin)
        facets = VODPlaybackSessionViewSet.as_view({"get": "facets"})(
            facets_request
        )

        self.assertEqual(facets.status_code, 200)
        self.assertIn(
            {"value": str(admin.id), "label": admin.username},
            facets.data["users"],
        )
        self.assertIn(
            {"value": str(self.account_a.id), "label": self.account_a.name},
            facets.data["accounts"],
        )
        self.assertIn(
            {
                "value": str(self.german.id),
                "label": self.german.name,
                "m3u_account": str(self.account_a.id),
            },
            facets.data["categories"],
        )

        stats_request = APIRequestFactory().get(
            "/api/vod/playback-sessions/stats/",
            {"user": str(admin.id), "category": str(self.german.id)},
        )
        force_authenticate(stats_request, user=admin)
        stats_response = VODPlaybackSessionViewSet.as_view({"get": "stats"})(
            stats_request
        )

        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(stats_response.data["sessions"], 1)
        self.assertEqual(stats_response.data["failover_sessions"], 1)
        self.assertEqual(stats_response.data["watched_seconds"], 90)
        self.assertEqual(stats_response.data["bytes_sent"], 1048576)

    @patch("apps.vod.tasks.cleanup_vod_playback_history.delay")
    @patch.object(
        CoreSettings,
        "set_vod_playback_history_retention_days",
        return_value=30,
    )
    def test_admin_can_configure_playback_history_retention(
        self,
        set_retention,
        cleanup_delay,
    ):
        admin = get_user_model().objects.create_user(
            username="history-retention-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().put(
            "/api/vod/playback-sessions/retention/",
            {"retention_days": 30},
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODPlaybackSessionViewSet.as_view({"put": "retention"})(
            request
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["retention_days"], 30)
        set_retention.assert_called_once_with(30)
        cleanup_delay.assert_called_once_with()

    def test_playback_history_bulk_delete_honors_filtered_select_all(self):
        admin = get_user_model().objects.create_user(
            username="history-delete-admin",
            password="test-password",
            user_level=10,
        )
        matching = record_playback_selection(
            session_id="history-delete-match",
            user=admin,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.FAILED,
        )
        retained = record_playback_selection(
            session_id="history-delete-retain",
            user=admin,
            relation=self.english_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        request = APIRequestFactory().post(
            "/api/vod/playback-sessions/bulk-delete/",
            {
                "select_all": True,
                "exclude_ids": [],
                "filters": {"status": "failed"},
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODPlaybackSessionViewSet.as_view(
            {"post": "bulk_delete"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["deleted_sessions"], 1)
        self.assertFalse(VODPlaybackSession.objects.filter(pk=matching.pk).exists())
        self.assertTrue(VODPlaybackSession.objects.filter(pk=retained.pk).exists())

    def test_non_admin_cannot_delete_playback_history(self):
        user = get_user_model().objects.create_user(
            username="history-viewer",
            password="test-password",
        )
        playback = record_playback_selection(
            session_id="history-delete-forbidden",
            user=user,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        request = APIRequestFactory().post(
            "/api/vod/playback-sessions/bulk-delete/",
            {"ids": [playback.id]},
            format="json",
        )
        force_authenticate(request, user=user)

        response = VODPlaybackSessionViewSet.as_view(
            {"post": "bulk_delete"}
        )(request)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(VODPlaybackSession.objects.filter(pk=playback.pk).exists())

    def test_playback_history_bulk_metadata_updates_each_source_once(self):
        admin = get_user_model().objects.create_user(
            username="history-metadata-admin",
            password="test-password",
            user_level=10,
        )
        first = record_playback_selection(
            session_id="history-metadata-first",
            user=admin,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        second = record_playback_selection(
            session_id="history-metadata-second",
            user=admin,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        request = APIRequestFactory().patch(
            "/api/vod/playback-sessions/bulk-metadata/",
            {
                "ids": [first.id, second.id],
                "updates": {
                    "resolution": {"mode": "set", "value": "1080p"},
                    "subtitle_languages": {
                        "mode": "set",
                        "value": ["deu"],
                    },
                },
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        with (
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ) as mark_outdated,
            patch(
                "apps.vod.profile_selection.enqueue_all_profile_selection_rebuilds"
            ) as enqueue_full_rebuild,
        ):
            response = VODPlaybackSessionViewSet.as_view(
                {"patch": "bulk_metadata"}
            )(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["selected_sessions"], 2)
        self.assertEqual(response.data["updated_sources"], 1)
        self.assertEqual(response.data["affected_titles"], 1)
        self.assertEqual(response.data["profile_update"], "outdated")
        mark_outdated.assert_called_once_with(
            trigger_reason="Playback-derived VOD source metadata was edited",
        )
        enqueue_full_rebuild.assert_not_called()
        self.german_relation.refresh_from_db()
        self.assertEqual(
            self.german_relation.manual_metadata["resolution"], "1080p"
        )
        self.assertEqual(
            self.german_relation.manual_metadata["subtitle_languages"], ["ger"]
        )
        self.assertIn("resolution", self.german_relation.locked_fields)

    def test_playback_history_episode_metadata_refreshes_parent_series_inline(self):
        admin = get_user_model().objects.create_user(
            username="history-episode-metadata-admin",
            password="test-password",
            user_level=10,
        )
        series = Series.objects.create(name="History Series", year=2026)
        episode = Episode.objects.create(
            series=series,
            season_number=1,
            episode_number=1,
            name="History Episode",
        )
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=self.german,
            external_series_id="history-series-source",
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="history-episode-source",
            container_extension="mkv",
        )
        playback = record_playback_selection(
            session_id="history-episode-metadata",
            user=admin,
            relation=episode_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        request = APIRequestFactory().patch(
            "/api/vod/playback-sessions/bulk-metadata/",
            {
                "ids": [playback.id],
                "updates": {
                    "subtitle_languages": {
                        "mode": "set",
                        "value": ["deu"],
                    },
                },
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        with patch(
            "apps.vod.profile_selection.mark_profile_selections_outdated"
        ) as mark_outdated:
            response = VODPlaybackSessionViewSet.as_view(
                {"patch": "bulk_metadata"}
            )(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["affected_titles"], 1)
        self.assertEqual(response.data["profile_update"], "outdated")
        mark_outdated.assert_called_once_with(
            trigger_reason="Playback-derived VOD source metadata was edited",
        )

    def test_playback_history_select_all_queues_one_full_profile_refresh(self):
        admin = get_user_model().objects.create_user(
            username="history-select-all-admin",
            password="test-password",
            user_level=10,
        )
        playback = record_playback_selection(
            session_id="history-select-all",
            user=admin,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        request = APIRequestFactory().patch(
            "/api/vod/playback-sessions/bulk-metadata/",
            {
                "select_all": True,
                "filters": {"user": str(admin.id)},
                "updates": {
                    "resolution": {"mode": "set", "value": "1080p"},
                },
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        with (
            patch("apps.vod.catalog_cache.bump_catalog_generation") as bump,
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ) as mark_outdated,
        ):
            response = VODPlaybackSessionViewSet.as_view(
                {"patch": "bulk_metadata"}
            )(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["selected_sessions"], 1)
        self.assertEqual(response.data["updated_sources"], 1)
        self.assertIsNone(response.data["affected_titles"])
        self.assertEqual(response.data["profile_update"], "outdated")
        self.german_relation.refresh_from_db()
        self.assertEqual(
            self.german_relation.manual_metadata["resolution"], "1080p"
        )
        bump.assert_called_once_with(invalidate_selections=False)
        mark_outdated.assert_called_once_with(
            trigger_reason="Playback-derived VOD source metadata was edited",
        )

    def test_playback_history_explicit_selection_queues_above_inline_limit(self):
        admin = get_user_model().objects.create_user(
            username="history-inline-limit-admin",
            password="test-password",
            user_level=10,
        )
        playback = record_playback_selection(
            session_id="history-inline-limit",
            user=admin,
            relation=self.german_relation,
            mode=VODPlaybackSession.Mode.PROXY,
            status=VODPlaybackSession.Status.COMPLETED,
        )
        request = APIRequestFactory().patch(
            "/api/vod/playback-sessions/bulk-metadata/",
            {
                "ids": [playback.id],
                "updates": {
                    "resolution": {"mode": "set", "value": "1080p"},
                },
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        with (
            patch("apps.vod.api_views.PLAYBACK_METADATA_INLINE_TITLE_LIMIT", 0),
            patch("apps.vod.catalog_cache.bump_catalog_generation") as bump,
            patch(
                "apps.vod.profile_selection.mark_profile_selections_outdated"
            ) as mark_outdated,
        ):
            response = VODPlaybackSessionViewSet.as_view(
                {"patch": "bulk_metadata"}
            )(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["affected_titles"])
        self.assertEqual(response.data["profile_update"], "outdated")
        bump.assert_called_once_with(invalidate_selections=False)
        mark_outdated.assert_called_once_with(
            trigger_reason="Playback-derived VOD source metadata was edited",
        )

    def test_metadata_precedence_is_category_provider_observed_manual(self):
        relation = self.german_relation
        M3UMovieRelation.objects.filter(pk=relation.pk).update(
            declared_metadata={
                "audio_languages": ["eng"],
                "resolution": "720p",
            },
            observed_metadata={"resolution": "1080p"},
            manual_metadata={"audio_languages": ["deu"]},
            locked_fields=["audio_languages"],
        )
        relation.refresh_from_db()

        effective = relation.effective_metadata(
            category_defaults={
                "audio_languages": ["fra"],
                "subtitle_languages": ["deu"],
                "resolution": "576p",
            },
            relation_declared={"resolution": "2160p"},
        )

        self.assertEqual(effective["values"]["audio_languages"], ["ger"])
        self.assertEqual(effective["provenance"]["audio_languages"], "manual")
        self.assertEqual(effective["values"]["resolution"], "1080p")
        self.assertEqual(effective["provenance"]["resolution"], "observed")
        self.assertEqual(effective["values"]["subtitle_languages"], ["ger"])
        self.assertEqual(
            effective["provenance"]["subtitle_languages"], "category"
        )

    def test_provider_list_exposes_metadata_for_each_exact_relation(self):
        admin = get_user_model().objects.create_user(
            username="vod-provider-list-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            f"/api/vod/movies/{self.movie.id}/providers/"
        )
        force_authenticate(request, user=admin)

        response = MovieViewSet.as_view({"get": "get_providers"})(
            request, pk=self.movie.id
        )

        self.assertEqual(response.status_code, 200)
        sources = {row["id"]: row for row in response.data}
        self.assertEqual(
            sources[self.german_relation.id]["source_metadata"]["values"][
                "audio_languages"
            ],
            ["ger"],
        )
        self.assertEqual(
            sources[self.english_relation.id]["source_metadata"]["values"][
                "resolution"
            ],
            "2160p",
        )

    def test_manual_metadata_only_updates_the_selected_source(self):
        admin = get_user_model().objects.create_user(
            username="vod-exact-source-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/manual-metadata/",
            {
                "content_type": "movie",
                "relation_id": self.german_relation.id,
                "metadata": {
                    "audio_languages": ["deu"],
                    "resolution": "720p",
                },
                "locked_fields": ["audio_languages", "resolution"],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.german_relation.refresh_from_db()
        self.english_relation.refresh_from_db()
        self.assertEqual(
            self.german_relation.manual_metadata["audio_languages"],
            ["ger"],
        )
        self.assertEqual(self.english_relation.manual_metadata, {})
        self.assertEqual(
            response.data["source_metadata"]["provenance"]["resolution"],
            "manual",
        )

    def test_manual_metadata_marks_ready_profiles_outdated(self):
        """Manual edits keep the last catalog active until explicit rebuild."""
        build_vod_profile_selection(self.policy.id)
        self.policy.refresh_from_db()
        self.assertEqual(
            list(
                VODMovieProfileSelection.objects.filter(
                    policy=self.policy,
                    generation=self.policy.active_selection_generation,
                ).values_list("relation_id", flat=True)
            ),
            [self.german_relation.id],
        )
        self.assertEqual(self.policy.selection_counts["output_entries"], 1)
        self.assertEqual(
            self.policy.selection_counts["movies"]["canonical_titles"], 1
        )
        admin = get_user_model().objects.create_user(
            username="vod-incremental-metadata-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/manual-metadata/",
            {
                "content_type": "movie",
                "relation_id": self.german_relation.id,
                "metadata": {"audio_languages": ["eng"]},
                "locked_fields": ["audio_languages"],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        with patch(
            "apps.vod.tasks.rebuild_all_vod_profile_selections.delay"
        ) as full_rebuild:
            response = VODSourceRelationViewSet.as_view(
                {"patch": "manual_metadata"}
            )(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["profile_update"], "outdated")
        self.assertEqual(response.data["profiles_affected"], 1)
        self.policy.refresh_from_db()
        self.assertEqual(
            self.policy.selection_status,
            VODAccessPolicy.SelectionStatus.OUTDATED,
        )
        self.assertTrue(
            VODMovieProfileSelection.objects.filter(
                policy=self.policy,
                generation=self.policy.active_selection_generation,
                movie=self.movie,
            ).exists()
        )
        self.assertEqual(self.policy.selection_counts["output_entries"], 1)
        self.assertEqual(
            self.policy.selection_counts["movies"]["canonical_titles"], 1
        )
        self.assertEqual(
            self.policy.selection_progress["phase"],
            "Catalog rebuild required",
        )
        full_rebuild.assert_not_called()

    def test_manual_metadata_rejects_provider_container_format(self):
        admin = get_user_model().objects.create_user(
            username="vod-format-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/manual-metadata/",
            {
                "content_type": "movie",
                "relation_id": self.german_relation.id,
                "metadata": {"container_extension": "mp4"},
                "locked_fields": ["container_extension"],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 400)
        self.assertIn("container_extension", str(response.data))

    def test_series_manual_metadata_updates_episode_sources_and_overview(self):
        series = Series.objects.create(name="Exact metadata series")
        category = VODCategory.objects.create(
            name="EXACT SERIES", category_type="series"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_a,
            category=category,
            enabled=True,
            metadata_defaults={
                "audio_languages": ["eng"],
                "subtitle_languages": ["eng"],
                "resolution": "720p",
            },
        )
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=category,
            external_series_id="exact-metadata-series",
        )
        episode = Episode.objects.create(
            series=series,
            name="Episode 1",
            season_number=1,
            episode_number=1,
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="exact-metadata-episode",
            container_extension="mkv",
        )
        admin = get_user_model().objects.create_user(
            username="vod-series-metadata-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/manual-metadata/",
            {
                "content_type": "series",
                "relation_id": series_relation.id,
                "metadata": {
                    "audio_languages": ["deu"],
                    "subtitle_languages": ["deu"],
                    "resolution": "1080p",
                },
                "locked_fields": [
                    "audio_languages",
                    "subtitle_languages",
                    "resolution",
                ],
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 200, response.data)
        series_relation.refresh_from_db()
        episode_relation.refresh_from_db()
        self.assertEqual(
            series_relation.manual_metadata["audio_languages"],
            ["ger"],
        )
        self.assertEqual(
            episode_relation.effective_metadata()["values"]["resolution"],
            "1080p",
        )
        self.assertEqual(episode_relation.manual_metadata, {})

        overview_request = APIRequestFactory().get(
            "/api/vod/", {"type": "series", "search": series.name}
        )
        force_authenticate(overview_request, user=admin)
        overview = UnifiedContentViewSet.as_view({"get": "list"})(
            overview_request
        )

        self.assertEqual(overview.status_code, 200, overview.data)
        row = overview.data["results"][0]
        self.assertEqual(row["source_metadata"]["audio_languages"], ["ger"])
        self.assertEqual(row["source_metadata"]["subtitle_languages"], ["ger"])
        self.assertEqual(row["source_metadata"]["resolutions"], ["1080p"])
        self.assertEqual(row["source_metadata"]["container_extensions"], ["mkv"])

    def test_series_overview_replaces_category_resolution_with_episode_video(self):
        series = Series.objects.create(name="Provider resolution series")
        category = VODCategory.objects.create(
            name="PROVIDER RESOLUTION SERIES",
            category_type="series",
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_a,
            category=category,
            enabled=True,
            metadata_defaults={"resolution": "1080p"},
        )
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=category,
            external_series_id="provider-resolution-series",
            declared_metadata={"resolution": "1080p"},
        )
        episode = Episode.objects.create(
            series=series,
            name="Episode 1",
            season_number=1,
            episode_number=1,
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=series_relation,
            stream_id="provider-resolution-episode",
            container_extension="mkv",
            custom_properties={
                "info": {
                    "info": {
                        "video": {
                            "codec_name": "h264",
                            "width": 640,
                            "height": 480,
                        }
                    }
                }
            },
        )
        admin = get_user_model().objects.create_user(
            username="vod-provider-resolution-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/", {"type": "series", "search": series.name}
        )
        force_authenticate(request, user=admin)

        response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        row = response.data["results"][0]
        self.assertEqual(row["source_count"], 1)
        self.assertEqual(row["source_metadata"]["resolutions"], ["480p"])

    def test_bulk_metadata_can_target_all_filtered_titles(self):
        other_movie = Movie.objects.create(name="Unrelated title", year=2026)
        other_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account_a,
            movie=other_movie,
            category=self.german,
            stream_id="other-43",
        )
        admin = get_user_model().objects.create_user(
            username="vod-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/bulk-manual-metadata/",
            {
                "select_all": True,
                "filters": {
                    "type": "movies",
                    "search": "Avatar",
                    "category": "",
                },
                "exclude_selections": [],
                "metadata": {"resolution": "1080p"},
            },
            format="json",
        )
        force_authenticate(request, user=admin)
        response = VODSourceRelationViewSet.as_view(
            {"patch": "bulk_manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.german_relation.refresh_from_db()
        self.english_relation.refresh_from_db()
        other_relation.refresh_from_db()
        self.assertEqual(
            self.german_relation.manual_metadata["resolution"],
            "1080p",
        )
        self.assertEqual(
            self.english_relation.manual_metadata["resolution"],
            "1080p",
        )
        self.assertEqual(other_relation.manual_metadata, {})

    def test_bulk_source_metadata_does_not_edit_canonical_titles(self):
        self.movie.name = "┃DE┃ Avatar"
        self.movie.save(update_fields=["name"])
        other_movie = Movie.objects.create(name="┃DE┃ Unrelated title")
        M3UMovieRelation.objects.create(
            m3u_account=self.account_a,
            movie=other_movie,
            category=self.german,
            stream_id="other-title",
        )
        admin = get_user_model().objects.create_user(
            username="vod-title-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/bulk-manual-metadata/",
            {
                "select_all": True,
                "filters": {"type": "movies", "search": "Avatar"},
                "exclude_selections": [],
                "metadata": {},
                "canonical_title": {"mode": "clean"},
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "bulk_manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 400, response.data)
        self.movie.refresh_from_db()
        other_movie.refresh_from_db()
        self.assertEqual(self.movie.display_name, "")
        self.assertEqual(other_movie.display_name, "")

    def test_bulk_title_regex_requires_a_pattern(self):
        admin = get_user_model().objects.create_user(
            username="vod-title-regex-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/bulk-manual-metadata/",
            {
                "selections": [{"content_type": "movie", "id": self.movie.id}],
                "metadata": {},
                "canonical_title": {"mode": "regex", "pattern": ""},
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "bulk_manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 400)

    def test_bulk_metadata_limits_selected_movie_to_filtered_account_and_category(self):
        admin = get_user_model().objects.create_user(
            username="vod-filtered-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/bulk-manual-metadata/",
            {
                "selections": [
                    {
                        "content_type": "movie",
                        "relation_id": self.german_relation.id,
                    },
                ],
                "filters": {
                    "type": "movies",
                    "search": "Avatar",
                    "category": f"{self.german.name}|movie",
                    "m3u_account": str(self.account_a.id),
                },
                "metadata": {"resolution": "1080p"},
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "bulk_manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated_sources"], 1)
        self.german_relation.refresh_from_db()
        self.english_relation.refresh_from_db()
        self.assertEqual(
            self.german_relation.manual_metadata["resolution"], "1080p"
        )
        self.assertEqual(self.english_relation.manual_metadata, {})

    def test_account_and_category_filters_require_one_matching_source_relation(self):
        admin = get_user_model().objects.create_user(
            username="vod-cross-filter-admin",
            password="test-password",
            user_level=10,
        )
        query = {
            "m3u_account": str(self.account_a.id),
            "category": f"{self.english.name}|movie",
            "page_size": 24,
        }

        for viewset in (MovieViewSet, UnifiedContentViewSet):
            request = APIRequestFactory().get("/api/vod/", query)
            force_authenticate(request, user=admin)
            response = viewset.as_view({"get": "list"})(request)

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 0)
            self.assertEqual(response.data["results"], [])

    def test_library_added_date_filters_standard_and_unified_lists(self):
        cutoff = timezone.now() - timedelta(days=7)
        self.movie.library_added_at = cutoff - timedelta(days=1)
        self.movie.save(update_fields=["library_added_at"])
        recent_movie = Movie.objects.create(
            name="Recently imported",
            library_added_at=cutoff + timedelta(days=1),
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account_a,
            movie=recent_movie,
            category=self.german,
            stream_id="recently-imported",
        )
        admin = get_user_model().objects.create_user(
            username="vod-library-date-admin",
            password="test-password",
            user_level=10,
        )
        query = {
            "type": "movies",
            "library_added_after": cutoff.isoformat(),
            "page_size": 24,
        }

        for viewset in (MovieViewSet, UnifiedContentViewSet):
            request = APIRequestFactory().get("/api/vod/", query)
            force_authenticate(request, user=admin)
            response = viewset.as_view({"get": "list"})(request)

            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(
                response.data["results"][0]["name"],
                recent_movie.name,
            )
            self.assertEqual(
                parse_datetime(
                    response.data["results"][0]["library_added_at"]
                ),
                recent_movie.library_added_at,
            )

        variant_request = APIRequestFactory().get(
            "/api/vod/",
            {
                **query,
                "representation": "variants",
            },
        )
        force_authenticate(variant_request, user=admin)
        variant_response = UnifiedContentViewSet.as_view({"get": "list"})(
            variant_request
        )

        self.assertEqual(variant_response.status_code, 200, variant_response.data)
        self.assertEqual(variant_response.data["count"], 1)
        self.assertEqual(
            variant_response.data["results"][0]["canonical_id"],
            recent_movie.id,
        )

    def test_unified_list_filters_genre_anime_and_adult_flags(self):
        self.movie.genre = ""
        self.movie.is_adult = False
        self.movie.tmdb_metadata = {
            "genres": [{"id": 878, "name": "Science Fiction"}],
            "is_anime": True,
            "adult": False,
        }
        self.movie.save(
            update_fields=["genre", "is_adult", "tmdb_metadata", "updated_at"]
        )
        admin = get_user_model().objects.create_user(
            username="vod-canonical-filter-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/",
            {
                "type": "movies",
                "genre": "science fiction",
                "anime_mode": "yes",
                "adult_mode": "no",
                "page_size": 24,
            },
        )
        force_authenticate(request, user=admin)

        response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id"], self.movie.id)
        self.assertNotIn("description", response.data["results"][0])

    def test_canonical_library_title_falls_back_to_clean_title(self):
        self.movie.display_name = "Provider Avatar"
        self.movie.clean_title = "Clean Avatar"
        self.movie.save(update_fields=["display_name", "clean_title"])
        admin = get_user_model().objects.create_user(
            username="vod-clean-title-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/", {"type": "movies", "page_size": 24}
        )
        force_authenticate(request, user=admin)

        response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["results"][0]["name"], "Clean Avatar")

    def test_canonical_library_keeps_processed_metadata_locked(self):
        CoreSettings.set_vod_metadata_settings(
            api_token="",
            languages=["de-DE", "en-US"],
            auto_enrich=False,
            match_missing=False,
            title_rules=[],
        )
        self.movie.clean_title = "Avatar"
        self.movie.tmdb_status = "missing_id"
        self.movie.tmdb_enrichment_signature = "processed-with-old-settings"
        self.movie.save(
            update_fields=[
                "clean_title",
                "tmdb_status",
                "tmdb_enrichment_signature",
            ]
        )
        CoreSettings.set_vod_metadata_settings(
            api_token="",
            languages=["en-US"],
            auto_enrich=True,
            match_missing=True,
            title_rules=["NF -"],
        )
        admin = get_user_model().objects.create_user(
            username="vod-lookup-lock-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/", {"type": "movies", "page_size": 24}
        )
        force_authenticate(request, user=admin)

        response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["results"][0]["metadata_auto_locked"])

    def test_unified_list_reports_movie_and_series_edition_counts(self):
        series = Series.objects.create(name="Avatar Series", year=2005)
        german_series = VODCategory.objects.create(
            name="GERMANY SERIES", category_type="series"
        )
        english_series = VODCategory.objects.create(
            name="NETFLIX SERIES", category_type="series"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_a,
            category=german_series,
            enabled=True,
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account_b,
            category=english_series,
            enabled=True,
        )
        german_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=german_series,
            external_series_id="series-a",
        )
        english_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account_b,
            series=series,
            category=english_series,
            external_series_id="series-b",
        )
        episode = Episode.objects.create(
            name="The Boy in the Iceberg",
            series=series,
            season_number=1,
            episode_number=1,
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=german_relation,
            stream_id="episode-a",
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account_b,
            episode=episode,
            series_relation=english_relation,
            stream_id="episode-b",
        )
        admin = get_user_model().objects.create_user(
            username="vod-source-count-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/", {"page_size": 24}
        )
        force_authenticate(request, user=admin)

        with CaptureQueriesContext(connection) as queries:
            response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200)
        page_queries = [
            query["sql"]
            for query in queries.captured_queries
            if "WITH unified_content AS" in query["sql"]
        ]
        self.assertEqual(len(page_queries), 1)
        self.assertIn("COUNT(*) OVER()", page_queries[0])
        self.assertNotIn("tmdb_metadata", page_queries[0])
        self.assertFalse(
            any(
                '"vod_movie"."tmdb_metadata"' in query["sql"]
                or '"vod_series"."tmdb_metadata"' in query["sql"]
                for query in queries.captured_queries
            )
        )
        counts = {
            (item["content_type"], item["name"]): item["source_count"]
            for item in response.data["results"]
        }
        self.assertEqual(counts[("movie", "Avatar")], 2)
        self.assertEqual(counts[("series", "Avatar Series")], 2)
        for item in response.data["results"]:
            self.assertNotIn("custom_properties", item)
            self.assertNotIn("tmdb", item)
            self.assertNotIn("description", item)

    def test_unified_variant_list_returns_each_exact_provider_source(self):
        self.german_relation.custom_properties = {
            "basic_data": {"name": "Provider A Avatar 1080p"}
        }
        self.german_relation.save(update_fields=["custom_properties"])
        self.english_relation.custom_properties = {
            "basic_data": {"name": "Provider B Avatar 4K"}
        }
        self.english_relation.save(update_fields=["custom_properties"])
        self.movie.display_name = "Avatar (2005)"
        self.movie.tmdb_match_id = "272"
        self.movie.save(update_fields=["display_name", "tmdb_match_id"])
        admin = get_user_model().objects.create_user(
            username="vod-variant-list-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/",
            {
                "type": "movies",
                "representation": "variants",
                "page_size": 24,
            },
        )
        force_authenticate(request, user=admin)

        with CaptureQueriesContext(connection) as queries:
            response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 2)
        rows = {row["relation_id"]: row for row in response.data["results"]}
        self.assertEqual(
            rows[self.german_relation.id]["name"],
            "Provider A Avatar 1080p",
        )
        self.assertEqual(
            rows[self.english_relation.id]["name"],
            "Provider B Avatar 4K",
        )
        self.assertEqual(
            rows[self.german_relation.id]["canonical_name"],
            "Avatar (2005)",
        )
        self.assertEqual(
            rows[self.german_relation.id]["uuid"],
            str(self.movie.uuid),
        )
        self.assertEqual(rows[self.german_relation.id]["tmdb_id"], "272")
        self.assertNotIn("tmdb", rows[self.german_relation.id])
        self.assertNotIn("description", rows[self.german_relation.id])
        self.assertFalse(
            any(
                '"vod_movie"."tmdb_metadata"' in query["sql"]
                or '"vod_series"."tmdb_metadata"' in query["sql"]
                for query in queries.captured_queries
            )
        )

    def test_missing_external_ids_includes_tvdb_and_wikidata(self):
        self.movie.tmdb_id = None
        self.movie.imdb_id = None
        self.movie.tmdb_match_id = ""
        self.movie.tmdb_imdb_id = ""
        self.movie.tmdb_metadata = {
            "external_ids": {"tvdb_id": "1234", "wikidata_id": "Q42"}
        }
        self.movie.save(
            update_fields=[
                "tmdb_id",
                "imdb_id",
                "tmdb_match_id",
                "tmdb_imdb_id",
                "tmdb_metadata",
            ]
        )
        admin = get_user_model().objects.create_user(
            username="vod-external-id-filter-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().get(
            "/api/vod/",
            {
                "type": "movies",
                "metadata_status": "missing_external_ids",
                "page_size": 24,
            },
        )
        force_authenticate(request, user=admin)

        response = UnifiedContentViewSet.as_view({"get": "list"})(request)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 0)

    def test_select_all_does_not_cross_match_account_and_category(self):
        admin = get_user_model().objects.create_user(
            username="vod-cross-bulk-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/bulk-manual-metadata/",
            {
                "select_all": True,
                "filters": {
                    "type": "movies",
                    "category": f"{self.english.name}|movie",
                    "m3u_account": str(self.account_a.id),
                },
                "exclude_selections": [],
                "metadata": {"resolution": "2160p"},
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "bulk_manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated_sources"], 0)
        self.german_relation.refresh_from_db()
        self.english_relation.refresh_from_db()
        self.assertEqual(self.german_relation.manual_metadata, {})
        self.assertEqual(self.english_relation.manual_metadata, {})

    def test_select_all_limits_series_and_episodes_to_filtered_account(self):
        series = Series.objects.create(name="Filtered series")
        series_category = VODCategory.objects.create(
            name="GERMAN SERIES", category_type="series"
        )
        other_category = VODCategory.objects.create(
            name="ENGLISH SERIES", category_type="series"
        )
        relation_a = M3USeriesRelation.objects.create(
            m3u_account=self.account_a,
            series=series,
            category=series_category,
            external_series_id="series-a",
        )
        relation_b = M3USeriesRelation.objects.create(
            m3u_account=self.account_b,
            series=series,
            category=other_category,
            external_series_id="series-b",
        )
        episode = Episode.objects.create(
            series=series,
            name="Episode 1",
            season_number=1,
            episode_number=1,
        )
        episode_a = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_a,
            episode=episode,
            series_relation=relation_a,
            stream_id="episode-a",
        )
        episode_b = M3UEpisodeRelation.objects.create(
            m3u_account=self.account_b,
            episode=episode,
            series_relation=relation_b,
            stream_id="episode-b",
        )
        admin = get_user_model().objects.create_user(
            username="vod-series-filtered-admin",
            password="test-password",
            user_level=10,
        )
        request = APIRequestFactory().patch(
            "/api/vod/source-relations/bulk-manual-metadata/",
            {
                "select_all": True,
                "filters": {
                    "type": "series",
                    "search": "Filtered",
                    "category": f"{series_category.name}|series",
                    "m3u_account": str(self.account_a.id),
                },
                "exclude_selections": [],
                "metadata": {"audio_languages": ["ger"]},
            },
            format="json",
        )
        force_authenticate(request, user=admin)

        response = VODSourceRelationViewSet.as_view(
            {"patch": "bulk_manual_metadata"}
        )(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated_sources"], 1)
        relation_a.refresh_from_db()
        relation_b.refresh_from_db()
        episode_a.refresh_from_db()
        episode_b.refresh_from_db()
        self.assertEqual(relation_a.manual_metadata["audio_languages"], ["ger"])
        self.assertEqual(
            episode_a.effective_metadata()["values"]["audio_languages"],
            ["ger"],
        )
        self.assertEqual(relation_b.manual_metadata, {})
        self.assertEqual(episode_b.manual_metadata, {})
