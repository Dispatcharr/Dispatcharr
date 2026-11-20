"""XC list endpoints handle wildcard and invalid category_id values (#1929)."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from apps.channels.models import Channel, ChannelGroup
from apps.m3u.models import M3UAccount
from apps.output.views import (
    _XC_NO_MATCHING_CATEGORY,
    _xc_normalize_category_id,
    xc_get_live_streams,
    xc_get_series,
    xc_get_vod_streams,
    xc_player_api,
)
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODCategory,
)

User = get_user_model()


class XCNormalizeCategoryIdTests(TestCase):
    def test_all_categories(self):
        for value in (None, "", "  ", "*", " * "):
            with self.subTest(value=value):
                self.assertIsNone(_xc_normalize_category_id(value))

    def test_valid_ids(self):
        self.assertEqual(_xc_normalize_category_id("12"), 12)
        self.assertEqual(_xc_normalize_category_id(" 7 "), 7)
        self.assertEqual(_xc_normalize_category_id(3), 3)

    def test_invalid_values(self):
        for value in ("abc", "1.5", "-1", "1,2"):
            with self.subTest(value=value):
                self.assertIs(
                    _xc_normalize_category_id(value), _XC_NO_MATCHING_CATEGORY
                )


class XCCategoryFilterEndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username="xcuser", password="testpass123")
        self.user.user_level = 10
        self.user.save()

        account = M3UAccount.objects.create(
            name="Provider",
            server_url="http://provider.example.com",
            username="u",
            password="p",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=1,
            custom_properties={"enable_vod": True},
        )

        self.series_cat_a = VODCategory.objects.create(name="Drama", category_type="series")
        self.series_cat_b = VODCategory.objects.create(name="Comedy", category_type="series")
        for name, cat, ext_id in (
            ("Show A", self.series_cat_a, "1"),
            ("Show B", self.series_cat_b, "2"),
        ):
            M3USeriesRelation.objects.create(
                m3u_account=account,
                series=Series.objects.create(name=name),
                category=cat,
                external_series_id=ext_id,
            )

        self.movie_cat_a = VODCategory.objects.create(name="Action", category_type="movie")
        self.movie_cat_b = VODCategory.objects.create(name="Horror", category_type="movie")
        for name, cat, stream_id in (
            ("Movie A", self.movie_cat_a, "10"),
            ("Movie B", self.movie_cat_b, "20"),
        ):
            M3UMovieRelation.objects.create(
                m3u_account=account,
                movie=Movie.objects.create(name=name),
                category=cat,
                stream_id=stream_id,
            )

        self.group_a = ChannelGroup.objects.create(name="News")
        self.group_b = ChannelGroup.objects.create(name="Sports")
        Channel.objects.create(name="Chan A", channel_number=1, channel_group=self.group_a)
        Channel.objects.create(name="Chan B", channel_number=2, channel_group=self.group_b)

    def _request(self, **params):
        return self.factory.get("/player_api.php", params)

    def _names(self, items):
        return sorted(item["name"] for item in items)

    def _assert_filters(self, fetch, cat_a_id, all_names, cat_a_names):
        cases = (
            (None, all_names),
            ("", all_names),
            ("*", all_names),
            (str(cat_a_id), cat_a_names),
            ("abc", []),
        )
        for category_id, expected in cases:
            with self.subTest(category_id=category_id):
                items = fetch(self._request(), self.user, category_id)
                self.assertEqual(self._names(items), expected)

    def test_get_series(self):
        self._assert_filters(
            xc_get_series, self.series_cat_a.id, ["Show A", "Show B"], ["Show A"]
        )

    def test_get_vod_streams(self):
        self._assert_filters(
            xc_get_vod_streams, self.movie_cat_a.id, ["Movie A", "Movie B"], ["Movie A"]
        )

    def test_get_live_streams(self):
        self._assert_filters(
            xc_get_live_streams, self.group_a.id, ["Chan A", "Chan B"], ["Chan A"]
        )

    def test_player_api_wildcard_returns_full_lists(self):
        """End to end through player_api.php, including the streamed live list."""
        expected = {
            "get_series": ["Show A", "Show B"],
            "get_vod_streams": ["Movie A", "Movie B"],
            "get_live_streams": ["Chan A", "Chan B"],
        }
        with patch("apps.output.views.authorize_xc_client", return_value=(self.user, None)):
            for action, names in expected.items():
                with self.subTest(action=action):
                    request = self._request(
                        username="xcuser", password="xc", action=action, category_id="*"
                    )
                    response = xc_player_api(request)
                    self.assertEqual(response.status_code, 200)
                    if response.streaming:
                        body = b"".join(response.streaming_content)
                    else:
                        body = response.content
                    self.assertEqual(self._names(json.loads(body)), names)
