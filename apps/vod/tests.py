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
        self.series = Series.objects.create(name="Avatar", year=2005)
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
