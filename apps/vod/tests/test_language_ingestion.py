"""Ingestion sets/clears the top-level `language` key on relation
custom_properties from provider-supplied metadata. Category-assigned
language is never touched here; it's applied at read time.
"""
from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
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
from apps.vod.tasks import batch_process_episodes, process_movie_batch, process_series_batch


class MovieLanguageIngestionTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Lang Movies",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(name="Movies", category_type="movie")
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category, m3u_account=self.account, enabled=True,
        )
        self.categories = {"10": self.category, "__uncategorized__": self.category}
        self.relations = {self.category.id: self.cat_relation}

    def _process(self, **row_overrides):
        row = {
            "stream_id": 9001,
            "name": "Provider Film",
            "category_id": "10",
            "container_extension": "mp4",
        }
        row.update(row_overrides)
        process_movie_batch(
            self.account, [row], self.categories, self.relations,
            scan_start_time=timezone.now(),
        )

    def test_two_letter_language_field_is_recorded(self):
        self._process(language="es")
        relation = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="9001")
        self.assertEqual(relation.custom_properties.get("language"), "es")

    def test_three_letter_language_is_normalised(self):
        self._process(language="spa")
        relation = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="9001")
        self.assertEqual(relation.custom_properties.get("language"), "es")

    def test_audio_language_field_used_when_language_absent(self):
        self._process(audio_language="fr")
        relation = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="9001")
        self.assertEqual(relation.custom_properties.get("language"), "fr")

    def test_no_provider_language_leaves_key_absent(self):
        self._process()
        relation = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="9001")
        self.assertNotIn("language", relation.custom_properties)

    def test_refresh_without_language_clears_previously_set_value(self):
        self._process(language="es")
        relation = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="9001")
        self.assertEqual(relation.custom_properties.get("language"), "es")

        # Provider stops reporting a language on the next scan.
        self._process()
        relation.refresh_from_db()
        self.assertNotIn("language", relation.custom_properties)

    def test_basic_data_and_detailed_fetched_untouched_by_language_key(self):
        self._process(language="es")
        relation = M3UMovieRelation.objects.get(m3u_account=self.account, stream_id="9001")
        self.assertIn("basic_data", relation.custom_properties)
        self.assertIn("detailed_fetched", relation.custom_properties)


class SeriesLanguageIngestionTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Lang Series",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.category = VODCategory.objects.create(name="Series", category_type="series")
        self.cat_relation = M3UVODCategoryRelation.objects.create(
            category=self.category, m3u_account=self.account, enabled=True,
        )
        self.categories = {"20": self.category, "__uncategorized__": self.category}
        self.relations = {self.category.id: self.cat_relation}

    def test_series_relation_records_provider_language(self):
        process_series_batch(
            self.account,
            [{
                "series_id": 7001,
                "name": "Provider Series",
                "category_id": "20",
                "language": "de",
            }],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )
        relation = M3USeriesRelation.objects.get(
            m3u_account=self.account, external_series_id="7001"
        )
        self.assertEqual(relation.custom_properties.get("language"), "de")

    def test_no_provider_language_leaves_key_absent(self):
        process_series_batch(
            self.account,
            [{"series_id": 7002, "name": "Plain Series", "category_id": "20"}],
            self.categories,
            self.relations,
            scan_start_time=timezone.now(),
        )
        relation = M3USeriesRelation.objects.get(
            m3u_account=self.account, external_series_id="7002"
        )
        self.assertNotIn("language", relation.custom_properties)


class EpisodeLanguageIngestionTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Lang Episodes",
            server_url="http://example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.series = Series.objects.create(name="Episode Lang Series", year=2001)
        self.series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id="8801",
        )

    def _episode(self, stream_id, **info_overrides):
        return {
            "id": str(stream_id),
            "title": "Ep",
            "episode_num": 1,
            "season": 1,
            "container_extension": "mp4",
            "info": {**info_overrides},
        }

    def test_language_inside_info_audio_is_recorded(self):
        batch_process_episodes(
            self.account,
            self.series,
            {"1": [self._episode(501, audio={"language": "eng"})]},
            series_relation=self.series_relation,
        )
        relation = M3UEpisodeRelation.objects.get(m3u_account=self.account, stream_id="501")
        self.assertEqual(relation.custom_properties.get("language"), "en")

    def test_no_language_present_leaves_key_absent(self):
        batch_process_episodes(
            self.account,
            self.series,
            {"1": [self._episode(502)]},
            series_relation=self.series_relation,
        )
        relation = M3UEpisodeRelation.objects.get(m3u_account=self.account, stream_id="502")
        self.assertNotIn("language", relation.custom_properties)
