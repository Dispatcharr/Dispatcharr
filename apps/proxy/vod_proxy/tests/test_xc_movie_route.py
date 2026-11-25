from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.vod.models import M3UMovieRelation, Movie


class StreamXcMovieRouteTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create(
            username="xtream-user",
            custom_properties={"xc_password": "secret"},
        )
        self.account = M3UAccount.objects.create(
            name="provider",
            account_type=M3UAccount.Types.STALKER,
            is_active=True,
            custom_properties={"enable_vod": True},
        )
        self.movie = Movie.objects.create(name="Example Movie")
        self.movie_relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            stream_id="provider-stream-1",
        )

    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.vod_proxy.views.stream_vod", return_value=HttpResponse("ok"))
    def test_stream_xc_movie_uses_relation_id_from_catalog(
        self,
        mock_stream_vod,
        _mock_network_access_allowed,
    ):
        from apps.proxy.vod_proxy.views import stream_xc_movie

        request = self.factory.get(
            f"/movie/{self.user.username}/secret/{self.movie_relation.id}.mp4"
        )

        response = stream_xc_movie(
            request,
            username=self.user.username,
            password="secret",
            stream_id=str(self.movie_relation.id),
            extension="mp4",
        )

        self.assertEqual(response.status_code, 200)
        mock_stream_vod.assert_called_once_with(
            request,
            "movie",
            self.movie.uuid,
            None,
            None,
            self.user,
            check_network=False,
        )

    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.vod_proxy.views.stream_vod", return_value=HttpResponse("ok"))
    def test_stream_xc_movie_falls_back_to_movie_id(
        self,
        mock_stream_vod,
        _mock_network_access_allowed,
    ):
        from apps.proxy.vod_proxy.views import stream_xc_movie

        request = self.factory.get(
            f"/movie/{self.user.username}/secret/{self.movie.id}.mp4"
        )

        response = stream_xc_movie(
            request,
            username=self.user.username,
            password="secret",
            stream_id=str(self.movie.id),
            extension="mp4",
        )

        self.assertEqual(response.status_code, 200)
        mock_stream_vod.assert_called_once_with(
            request,
            "movie",
            self.movie.uuid,
            None,
            None,
            self.user,
            check_network=False,
        )

    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.vod_proxy.views.stream_vod", return_value=HttpResponse("ok"))
    def test_stream_xc_movie_rejects_disabled_vod_accounts(
        self,
        mock_stream_vod,
        _mock_network_access_allowed,
    ):
        from apps.proxy.vod_proxy.views import stream_xc_movie

        self.account.custom_properties = {"enable_vod": False}
        self.account.save(update_fields=["custom_properties"])

        request = self.factory.get(
            f"/movie/{self.user.username}/secret/{self.movie_relation.id}.mp4"
        )

        response = stream_xc_movie(
            request,
            username=self.user.username,
            password="secret",
            stream_id=str(self.movie_relation.id),
            extension="mp4",
        )

        self.assertEqual(response.status_code, 404)
        mock_stream_vod.assert_not_called()
