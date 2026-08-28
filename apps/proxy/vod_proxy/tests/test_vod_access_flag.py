"""XC VOD playback refuses users whose VOD access flags are off."""

from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.vod.models import (
    Episode,
    M3UEpisodeRelation,
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
)
from apps.vod.utils import is_vod_movies_enabled, is_vod_series_enabled


class IsVodMoviesEnabledTests(TestCase):
    def test_defaults_to_enabled_when_flag_absent(self):
        user = User(custom_properties={"xc_password": "x"})
        self.assertTrue(is_vod_movies_enabled(user=user))

    def test_null_custom_properties_is_enabled(self):
        user = User(custom_properties=None)
        self.assertTrue(is_vod_movies_enabled(user=user))

    def test_only_json_false_disables(self):
        """A truthy or missing value must not lock a user out by accident."""
        for value in (True, "false", 0, None):
            with self.subTest(value=value):
                user = User(custom_properties={"vod_movies_enabled": value})
                self.assertEqual(
                    is_vod_movies_enabled(user=user), value is not False
                )

    def test_no_user_is_not_restricted(self):
        self.assertTrue(is_vod_movies_enabled(user=None))


class IsVodSeriesEnabledTests(TestCase):
    def test_defaults_to_enabled_when_flag_absent(self):
        user = User(custom_properties={"xc_password": "x"})
        self.assertTrue(is_vod_series_enabled(user=user))

    def test_each_flag_only_gates_its_own_kind(self):
        user = User(custom_properties={"vod_movies_enabled": False})
        self.assertFalse(is_vod_movies_enabled(user=user))
        self.assertTrue(is_vod_series_enabled(user=user))

        user = User(custom_properties={"vod_series_enabled": False})
        self.assertTrue(is_vod_movies_enabled(user=user))
        self.assertFalse(is_vod_series_enabled(user=user))


class XcVodStreamAccessTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name=f"vod-play-{uuid4().hex[:6]}",
            server_url="http://example.com",
            priority=1,
            is_active=True,
        )
        self.movie = Movie.objects.create(name="Blocked Movie")
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            stream_id="movie-1",
            container_extension="mp4",
        )
        series = Series.objects.create(name="Blocked Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=self.account, series=series, external_series_id="series-1"
        )
        self.episode = Episode.objects.create(
            series=series, name="Pilot", season_number=1, episode_number=1
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=self.episode,
            series_relation=series_relation,
            stream_id="episode-1",
            container_extension="mkv",
        )

    def _user(self, **custom_properties):
        username = f"xc-play-{uuid4().hex[:8]}"
        props = {"xc_password": "xcpass"}
        props.update(custom_properties)
        User.objects.create_user(
            username=username, password="pass", user_level=0, custom_properties=props
        )
        return username

    def test_movie_playback_is_forbidden_when_movies_are_off(self):
        username = self._user(vod_movies_enabled=False)
        response = self.client.get(f"/movie/{username}/xcpass/{self.movie.id}.mp4")
        self.assertEqual(response.status_code, 403)

    def test_episode_playback_is_forbidden_when_series_are_off(self):
        username = self._user(vod_series_enabled=False)
        response = self.client.get(f"/series/{username}/xcpass/{self.episode.id}.mkv")
        self.assertEqual(response.status_code, 403)

    def test_disabling_movies_does_not_block_episodes(self):
        """The two flags are independent on the playback path as well."""
        username = self._user(vod_movies_enabled=False)
        response = self.client.get(f"/series/{username}/xcpass/{self.episode.id}.mkv")
        self.assertNotEqual(response.status_code, 403)

    def test_bad_password_is_rejected_before_the_access_flags(self):
        username = self._user(vod_movies_enabled=False)
        response = self.client.get(f"/movie/{username}/wrong/{self.movie.id}.mp4")
        self.assertEqual(response.status_code, 401)


class NativeVodHeadAccessTests(TestCase):
    """Native /proxy/vod HEAD uses the same flags as GET."""

    def setUp(self):
        self.factory = APIRequestFactory()
        account = M3UAccount.objects.create(
            name=f"vod-head-{uuid4().hex[:6]}",
            server_url="http://example.com",
            priority=1,
            is_active=True,
        )
        self.movie = Movie.objects.create(name="Head Blocked Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=self.movie,
            stream_id="movie-head-1",
            container_extension="mp4",
        )
        series = Series.objects.create(name="Head Blocked Series")
        series_relation = M3USeriesRelation.objects.create(
            m3u_account=account, series=series, external_series_id="series-head-1"
        )
        self.episode = Episode.objects.create(
            series=series, name="Pilot", season_number=1, episode_number=1
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=account,
            episode=self.episode,
            series_relation=series_relation,
            stream_id="episode-head-1",
            container_extension="mkv",
        )

    def _user(self, **custom_properties):
        return User.objects.create_user(
            username=f"vod-head-{uuid4().hex[:8]}",
            password="pass",
            user_level=1,
            custom_properties=custom_properties,
        )

    def _head(self, content_type, content_id, user=None):
        from apps.proxy.vod_proxy.views import head_vod

        request = self.factory.head(
            f"/proxy/vod/{content_type}/{content_id}",
            HTTP_USER_AGENT="test-agent",
        )
        if user is not None:
            force_authenticate(request, user=user)
        return head_vod(request, content_type=content_type, content_id=str(content_id))

    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_head_movie_is_forbidden_when_movies_are_off(self, _network_ok):
        user = self._user(vod_movies_enabled=False)
        response = self._head("movie", self.movie.uuid, user)
        self.assertEqual(response.status_code, 403)

    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_head_episode_is_forbidden_when_series_are_off(self, _network_ok):
        user = self._user(vod_series_enabled=False)
        response = self._head("episode", self.episode.uuid, user)
        self.assertEqual(response.status_code, 403)

    @patch("apps.proxy.vod_proxy.views._select_vod_stream", return_value=None)
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_head_disabling_movies_does_not_block_episodes(self, _network_ok, _select):
        user = self._user(vod_movies_enabled=False)
        response = self._head("episode", self.episode.uuid, user)
        self.assertNotEqual(response.status_code, 403)

    @patch("apps.proxy.vod_proxy.views._select_vod_stream", return_value=None)
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_head_anonymous_is_not_restricted_by_flags(self, _network_ok, _select):
        """No authenticated user means nothing to tie a flag to."""
        response = self._head("movie", self.movie.uuid)
        self.assertNotEqual(response.status_code, 403)
