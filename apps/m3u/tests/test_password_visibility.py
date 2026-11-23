"""M3U account password visibility for admin vs standard users."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.m3u.api_views import M3UAccountViewSet
from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountProfileSerializer, M3UAccountSerializer
from apps.vod.api_views import MovieViewSet
from apps.vod.models import (
    Episode, M3UEpisodeRelation, M3UMovieRelation, M3USeriesRelation, Movie, Series,
)
from apps.vod.serializers import (
    M3UEpisodeRelationSerializer, M3UMovieRelationSerializer, M3USeriesRelationSerializer,
)


class M3UPasswordVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="m3u_pwd_admin",
            password="x",
            user_level=User.UserLevel.ADMIN,
        )
        self.standard = User.objects.create_user(
            username="m3u_pwd_user",
            password="x",
            user_level=User.UserLevel.STANDARD,
        )
        self.streamer = User.objects.create_user(
            username="m3u_pwd_streamer", password="x", user_level=User.UserLevel.STREAMER
        )
        self.account = M3UAccount.objects.create(
            name="XC Acc",
            server_url="http://example.test/get.php?username=xcuser&password=super-secret",
            account_type="XC",
            username="xcuser",
            password="super-secret",
            status=M3UAccount.Status.ERROR,
            last_message="Failed: password=super-secret",
        )
        self.profile = self.account.profiles.get(is_default=True)
        self.profile.search_pattern = "xcuser/super-secret"
        self.profile.replace_pattern = "other-user/other-secret"
        self.profile.custom_properties = {"user_info": {"password": "super-secret"}}
        self.profile.save()
        self.factory = APIRequestFactory()

    def test_admin_sees_password(self):
        request = self.factory.get("/api/m3u/accounts/")
        request.user = self.admin
        data = M3UAccountSerializer(
            self.account, context={"request": request}
        ).data
        self.assertEqual(data.get("password"), "super-secret")

    def test_standard_user_does_not_see_password(self):
        request = self.factory.get("/api/m3u/accounts/")
        request.user = self.standard
        data = M3UAccountSerializer(
            self.account, context={"request": request}
        ).data
        self.assertNotIn("password", data)
        self.assertNotIn("server_url", data)
        self.assertNotIn("username", data)
        self.assertNotIn("custom_properties", data)
        self.assertNotIn("replace_pattern", data["profiles"][0])
        self.assertNotIn("custom_properties", data["profiles"][0])

    def test_profile_endpoint_preserves_admin_fields(self):
        request = self.factory.get("/")
        request.user = self.admin
        data = M3UAccountProfileSerializer(self.profile, context={"request": request}).data
        self.assertEqual(data["replace_pattern"], "other-user/other-secret")
        self.assertEqual(data["custom_properties"]["user_info"]["password"], "super-secret")

    def test_nested_vod_account_fails_closed_without_request_context(self):
        movie = Movie.objects.create(name="Test Movie")
        relation = M3UMovieRelation.objects.create(
            movie=movie, m3u_account=self.account, stream_id="1"
        )
        data = M3UMovieRelationSerializer(relation).data["m3u_account"]
        self.assertNotIn("server_url", data)
        self.assertNotIn("custom_properties", data["profiles"][0])

    def test_nested_vod_account_preserves_admin_response(self):
        movie = Movie.objects.create(name="Test Movie")
        relation = M3UMovieRelation.objects.create(
            movie=movie, m3u_account=self.account, stream_id="1"
        )
        request = self.factory.get("/")
        request.user = self.admin
        data = M3UMovieRelationSerializer(relation, context={"request": request}).data
        self.assertEqual(data["m3u_account"]["password"], "super-secret")

    def test_series_and_episode_relations_hide_non_admin_secrets(self):
        series = Series.objects.create(name="Test Series")
        episode = Episode.objects.create(name="Test Episode", series=series)
        series_relation = M3USeriesRelation.objects.create(
            series=series, m3u_account=self.account, external_series_id="series-1"
        )
        episode_relation = M3UEpisodeRelation.objects.create(
            episode=episode, m3u_account=self.account, stream_id="episode-1"
        )
        request = self.factory.get("/")
        request.user = self.standard
        for serializer, relation in (
            (M3USeriesRelationSerializer, series_relation),
            (M3UEpisodeRelationSerializer, episode_relation),
        ):
            with self.subTest(serializer=serializer.__name__):
                data = serializer(relation, context={"request": request}).data
                self.assertNotIn("super-secret", str(data["m3u_account"]))
                self.assertNotIn("other-secret", str(data["m3u_account"]))

    @patch("apps.accounts.permissions.network_access_allowed", return_value=True)
    def test_standard_account_list_hides_secrets_but_keeps_safe_status(self, _network):
        request = self.factory.get("/api/m3u/accounts/")
        force_authenticate(request, user=self.standard)
        response = M3UAccountViewSet.as_view({"get": "list"})(request)
        self.assertEqual(response.status_code, 200)
        account = next(item for item in response.data if item["id"] == self.account.id)
        self.assertNotIn("super-secret", str(account))
        self.assertNotIn("other-secret", str(account))
        self.assertEqual(account["last_message"], "M3U refresh failed. Contact an administrator.")

    @patch("apps.accounts.permissions.network_access_allowed", return_value=True)
    def test_movie_provider_endpoint_keeps_admin_access_and_hides_streamer_secrets(self, _network):
        movie = Movie.objects.create(name="Test Movie")
        M3UMovieRelation.objects.create(movie=movie, m3u_account=self.account, stream_id="1")
        view = MovieViewSet.as_view({"get": "get_providers"})
        for user in (self.streamer, self.standard, self.admin):
            with self.subTest(user=user.username):
                request = self.factory.get(f"/api/vod/movies/{movie.id}/providers/")
                force_authenticate(request, user=user)
                response = view(request, pk=movie.id)
                self.assertEqual(response.status_code, 200)
                account = response.data[0]["m3u_account"]
                if user == self.admin:
                    self.assertEqual(account["password"], "super-secret")
                    self.assertEqual(account["last_message"], "Failed: password=super-secret")
                else:
                    self.assertNotIn("super-secret", str(account))
                    self.assertNotIn("other-secret", str(account))
