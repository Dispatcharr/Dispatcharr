"""Regression tests for relation-specific series selection."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.vod.api_views import SeriesViewSet
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3USeriesRelation,
    Series,
    VODCategory,
)
from apps.vod.tasks import refresh_series_episodes


class SeriesProviderInfoTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(
            username="series-api-user",
            password="password",
        )
        self.account = M3UAccount.objects.create(
            name="Shared provider",
            server_url="http://example.com",
            is_active=True,
        )
        self.netflix = VODCategory.objects.create(
            name="NETFLIX Kids", category_type="series"
        )
        self.german = VODCategory.objects.create(
            name="German Kinder", category_type="series"
        )
        self.series = Series.objects.create(
            name="DE - Avatar: Der Herr der Elemente (US)",
            year=2005,
        )
        relation_defaults = {
            "m3u_account": self.account,
            "series": self.series,
            "custom_properties": {
                "episodes_fetched": True,
                "detailed_fetched": True,
            },
            "last_episode_refresh": timezone.now(),
        }
        self.netflix_series = M3USeriesRelation.objects.create(
            **relation_defaults,
            category=self.netflix,
            external_series_id="netflix-avatar",
        )
        self.german_series = M3USeriesRelation.objects.create(
            **relation_defaults,
            category=self.german,
            external_series_id="german-avatar",
        )
        self.netflix_series.custom_properties = {
            "episodes_fetched": True,
            "detailed_fetched": True,
            "detailed_info": {
                "name": "Avatar: The Last Airbender",
                "o_name": "Avatar: The Last Airbender",
            },
        }
        self.netflix_series.save(update_fields=["custom_properties"])
        self.german_series.custom_properties = {
            "episodes_fetched": True,
            "detailed_fetched": True,
            "detailed_info": {
                "name": "Avatar: Der Herr der Elemente (US)",
                "o_name": "Avatar: The Last Airbender",
            },
        }
        self.german_series.save(update_fields=["custom_properties"])
        episode = Episode.objects.create(
            series=self.series,
            season_number=1,
            episode_number=1,
            name="Canonical title",
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            series_relation=self.netflix_series,
            stream_id="netflix-episode-1",
            custom_properties={
                "info": {
                    "episode_num": 1,
                    "title": "NF - The Boy in the Iceberg",
                    "info": {"plot": "Netflix plot"},
                }
            },
        )
        self.german_episode = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            series_relation=self.german_series,
            stream_id="german-episode-1",
            custom_properties={
                "info": {
                    "episode_num": 1,
                    "title": "DE - Der Junge im Eisberg",
                    "info": {"plot": "German plot"},
                }
            },
        )

    def _get(self, action, params=None):
        request = self.factory.get("/api/vod/series/1/", params or {})
        force_authenticate(request, user=self.user)
        view = SeriesViewSet.as_view({"get": action})
        return view(request, pk=self.series.id)

    def test_provider_info_uses_selected_series_relation_for_episode_data(self):
        response = self._get(
            "series_info", {"relation_id": self.german_series.id}
        )
        selected_episode = response.data["episodes"]["1"][0]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["category_name"], "German Kinder")
        self.assertEqual(
            response.data["name"],
            "Avatar: Der Herr der Elemente (US)",
        )
        self.assertEqual(response.data["o_name"], "Avatar: The Last Airbender")
        self.assertEqual(selected_episode["relation_id"], self.german_episode.id)
        self.assertEqual(selected_episode["stream_id"], "german-episode-1")
        self.assertEqual(selected_episode["title"], "DE - Der Junge im Eisberg")
        self.assertEqual(selected_episode["plot"], "German plot")

    def test_provider_list_includes_category_for_each_relation(self):
        response = self._get("get_providers")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [provider["category"]["name"] for provider in response.data],
            ["NETFLIX Kids", "German Kinder"],
        )

    def test_provider_info_preserves_raw_series_name_as_final_fallback(self):
        self.german_series.custom_properties = {
            "episodes_fetched": True,
            "detailed_fetched": True,
            "detailed_info": {},
        }
        self.german_series.save(update_fields=["custom_properties"])

        response = self._get(
            "series_info", {"relation_id": self.german_series.id}
        )

        self.assertEqual(
            response.data["name"],
            "DE - Avatar: Der Herr der Elemente (US)",
        )

    def test_provider_info_backfills_details_missing_from_older_relations(self):
        self.german_series.custom_properties = {
            "episodes_fetched": True,
            "detailed_fetched": True,
        }
        self.german_series.save(update_fields=["custom_properties"])

        def store_details(_account, _series, _external_series_id):
            self.german_series.custom_properties = {
                "episodes_fetched": True,
                "detailed_fetched": True,
                "detailed_info": {
                    "name": "Avatar: Der Herr der Elemente (US)"
                },
            }
            self.german_series.save(update_fields=["custom_properties"])

        with patch(
            "apps.vod.tasks.refresh_series_episodes",
            side_effect=store_details,
        ) as refresh:
            response = self._get(
                "series_info", {"relation_id": self.german_series.id}
            )

        refresh.assert_called_once()
        self.assertEqual(
            response.data["name"],
            "Avatar: Der Herr der Elemente (US)",
        )


class SeriesRefreshDetailsTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Series detail provider",
            server_url="http://example.com",
            username="user",
            password="password",
            account_type=M3UAccount.Types.XC,
            is_active=True,
        )
        self.series = Series.objects.create(
            name="NF - Avatar: The Last Airbender",
            year=2005,
        )
        self.relation = M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id="avatar-netflix",
            custom_properties={"basic_data": {"name": self.series.name}},
        )

    def test_refresh_stores_relation_specific_series_details(self):
        client = MagicMock()
        client.get_series_info.return_value = {
            "info": {
                "name": "Avatar: The Last Airbender",
                "o_name": "Avatar: The Last Airbender",
                "plot": "Provider plot",
            },
            "episodes": {},
        }
        client_context = MagicMock()
        client_context.__enter__.return_value = client

        with (
            patch.object(
                self.account,
                "get_user_agent",
                return_value=SimpleNamespace(user_agent="Test Agent"),
            ),
            patch(
                "apps.vod.tasks.XtreamCodesClient",
                return_value=client_context,
            ),
            patch("apps.vod.tasks.batch_process_episodes"),
        ):
            refresh_series_episodes(
                self.account,
                self.series,
                self.relation.external_series_id,
            )

        self.relation.refresh_from_db()
        self.assertEqual(
            self.relation.custom_properties["detailed_info"]["name"],
            "Avatar: The Last Airbender",
        )
        self.assertEqual(
            self.relation.custom_properties["detailed_info"]["o_name"],
            "Avatar: The Last Airbender",
        )
        self.assertTrue(self.relation.custom_properties["episodes_fetched"])
        self.assertTrue(self.relation.custom_properties["detailed_fetched"])
