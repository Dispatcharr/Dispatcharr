"""M3UMovieRelationSerializer / M3UEpisodeRelationSerializer.get_quality_info:
category default quality as the final fallback before None. Also covers
M3UVODCategoryRelationSerializer's language/quality validation.
"""
from django.test import TestCase
from rest_framework import serializers as drf_serializers

from apps.m3u.models import M3UAccount
from apps.vod.language import invalidate_category_metadata_cache
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
from apps.vod.serializers import (
    M3UEpisodeRelationSerializer,
    M3UMovieRelationSerializer,
    M3UVODCategoryRelationSerializer,
)


class MovieQualityInfoCategoryFallbackTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)

        self.account = M3UAccount.objects.create(
            name="Quality Provider",
            server_url="http://example.com",
            username="u",
            password="p",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.category = VODCategory.objects.create(name="720p Category", category_type="movie")
        M3UVODCategoryRelation.objects.create(
            category=self.category, m3u_account=self.account, enabled=True,
            custom_properties={"quality": "720p"},
        )
        self.movie = Movie.objects.create(name="Plain Title Movie", year=2020)

    def test_falls_back_to_category_default_quality(self):
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, category=self.category,
            stream_id="q-1", container_extension="mp4",
        )
        info = M3UMovieRelationSerializer().get_quality_info(relation)
        self.assertEqual(info, {"quality": "720p"})

    def test_title_match_still_wins_over_category_default(self):
        movie_1080p = Movie.objects.create(name="Explicit Title 1080p", year=2021)
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=movie_1080p, category=self.category,
            stream_id="q-2", container_extension="mp4",
        )
        info = M3UMovieRelationSerializer().get_quality_info(relation)
        self.assertEqual(info, {"quality": "1080p"})

    def test_relation_custom_properties_quality_still_wins(self):
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, category=self.category,
            stream_id="q-3", container_extension="mp4",
            custom_properties={"quality": "4K"},
        )
        info = M3UMovieRelationSerializer().get_quality_info(relation)
        self.assertEqual(info, {"quality": "4K"})

    def test_no_category_default_and_no_match_returns_none(self):
        uncategorized = M3UMovieRelation.objects.create(
            m3u_account=self.account, movie=self.movie, category=None,
            stream_id="q-4", container_extension="mp4",
        )
        info = M3UMovieRelationSerializer().get_quality_info(uncategorized)
        self.assertIsNone(info)


class EpisodeQualityInfoCategoryFallbackTests(TestCase):
    def setUp(self):
        invalidate_category_metadata_cache()
        self.addCleanup(invalidate_category_metadata_cache)

        self.account = M3UAccount.objects.create(
            name="Episode Quality Provider",
            server_url="http://example.com",
            username="u",
            password="p",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.category = VODCategory.objects.create(name="480p Series Category", category_type="series")
        M3UVODCategoryRelation.objects.create(
            category=self.category, m3u_account=self.account, enabled=True,
            custom_properties={"quality": "480p"},
        )
        self.series = Series.objects.create(name="Quality Series", year=2019)
        self.series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=self.series, category=self.category,
            external_series_id="s-1",
        )
        self.episode = Episode.objects.create(
            series=self.series, name="Plain Episode Title", season_number=1, episode_number=1,
        )

    def test_falls_back_to_category_default_via_series_relation(self):
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, series_relation=self.series_relation,
            stream_id="eq-1", container_extension="mp4",
        )
        info = M3UEpisodeRelationSerializer().get_quality_info(relation)
        self.assertEqual(info, {"quality": "480p"})

    def test_no_series_relation_skips_category_lookup_without_error(self):
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account, episode=self.episode, series_relation=None,
            stream_id="eq-2", container_extension="mp4",
        )
        info = M3UEpisodeRelationSerializer().get_quality_info(relation)
        self.assertIsNone(info)


class CategoryRelationSerializerValidationTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Validation Provider",
            server_url="http://example.com",
            username="u",
            password="p",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.category = VODCategory.objects.create(name="Validated Category", category_type="movie")

    def test_valid_language_normalised_lowercase(self):
        serializer = M3UVODCategoryRelationSerializer(
            data={
                "category": self.category.id,
                "m3u_account": self.account.id,
                "enabled": True,
                "custom_properties": {"language": "ES"},
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["custom_properties"]["language"], "es")

    def test_invalid_language_is_rejected(self):
        serializer = M3UVODCategoryRelationSerializer(
            data={
                "category": self.category.id,
                "m3u_account": self.account.id,
                "enabled": True,
                "custom_properties": {"language": "eng"},
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("custom_properties", serializer.errors)

    def test_invalid_quality_is_rejected(self):
        serializer = M3UVODCategoryRelationSerializer(
            data={
                "category": self.category.id,
                "m3u_account": self.account.id,
                "enabled": True,
                "custom_properties": {"quality": "not-a-quality"},
            }
        )
        self.assertFalse(serializer.is_valid())
