"""Read-only preview availability, scoped to account and content type."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount, Stream
from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Movie,
    Series,
    VODCategory,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UVODCategoryRelation,
)


class ContentAvailabilityTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="Preview account", account_type="XC"
        )
        self.other = M3UAccount.objects.create(name="Other account", account_type="XC")
        self.admin = get_user_model().objects.create_user(
            username="preview-admin", user_level=10
        )
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = (
            f"/api/m3u/accounts/{self.account.id}/group-rules/content-availability/"
        )

    def test_empty_categories_are_not_available_even_when_enabled(self):
        group = ChannelGroup.objects.create(name="Empty live")
        ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account, channel_group=group, enabled=True
        )
        category = VODCategory.objects.create(
            name="Empty movies", category_type="movie"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account, category=category, enabled=True
        )
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"live": [], "movie": [], "series": []})

    def test_imported_content_is_available_without_changing_disabled_categories(self):
        group = ChannelGroup.objects.create(name="Imported live")
        live_relation = ChannelGroupM3UAccount.objects.create(
            m3u_account=self.account, channel_group=group, enabled=False
        )
        for index in range(2):
            Stream.objects.create(
                name=f"Live {index}",
                url=f"https://example.invalid/{index}",
                m3u_account=self.account,
                channel_group=group,
            )
        movie_category = VODCategory.objects.create(
            name="Imported movies", category_type="movie"
        )
        movie_category_relation = M3UVODCategoryRelation.objects.create(
            m3u_account=self.account, category=movie_category, enabled=False
        )
        M3UMovieRelation.objects.create(
            movie=Movie.objects.create(name="Movie"),
            m3u_account=self.account,
            category=movie_category,
            stream_id="movie",
        )
        series_category = VODCategory.objects.create(
            name="Imported series", category_type="series"
        )
        M3UVODCategoryRelation.objects.create(
            m3u_account=self.account, category=series_category, enabled=False
        )
        M3USeriesRelation.objects.create(
            series=Series.objects.create(name="Series"),
            m3u_account=self.account,
            category=series_category,
            external_series_id="series",
        )
        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        self.assertEqual(
            response.data,
            {
                "live": [group.id],
                "movie": [movie_category.id],
                "series": [series_category.id],
            },
        )
        live_relation.refresh_from_db()
        movie_category_relation.refresh_from_db()
        self.assertFalse(live_relation.enabled)
        self.assertFalse(movie_category_relation.enabled)

    def test_other_accounts_do_not_make_a_category_available(self):
        group = ChannelGroup.objects.create(name="Other live")
        Stream.objects.create(
            name="Private",
            url="https://example.invalid/private",
            m3u_account=self.other,
            channel_group=group,
        )
        category = VODCategory.objects.create(
            name="Other movies", category_type="movie"
        )
        M3UMovieRelation.objects.create(
            movie=Movie.objects.create(name="Private movie"),
            m3u_account=self.other,
            category=category,
            stream_id="private",
        )
        self.assertEqual(
            self.client.get(self.url).data, {"live": [], "movie": [], "series": []}
        )

    def test_missing_account_returns_not_found(self):
        self.assertEqual(
            self.client.get(
                "/api/m3u/accounts/999999/group-rules/content-availability/"
            ).status_code,
            404,
        )

    def test_non_admin_cannot_inspect_availability(self):
        user = get_user_model().objects.create_user(
            username="preview-viewer", user_level=0
        )
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get(self.url).status_code, 403)
