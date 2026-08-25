"""XC VOD playback refuses users whose VOD access flags are off."""

from uuid import uuid4

from django.test import TestCase

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
from apps.vod.utils import (
    VOD_KIND_MOVIE,
    VOD_KIND_SERIES,
    is_vod_enabled,
    vod_kind_for_content_type,
)


class IsVodEnabledTests(TestCase):
    def test_defaults_to_enabled_when_flags_absent(self):
        user = User(custom_properties={"xc_password": "x"})
        self.assertTrue(is_vod_enabled(kind=VOD_KIND_MOVIE, user=user))
        self.assertTrue(is_vod_enabled(kind=VOD_KIND_SERIES, user=user))

    def test_null_custom_properties_is_enabled(self):
        user = User(custom_properties=None)
        self.assertTrue(is_vod_enabled(kind=VOD_KIND_MOVIE, user=user))

    def test_each_flag_only_gates_its_own_kind(self):
        user = User(custom_properties={"vod_movies_enabled": False})
        self.assertFalse(is_vod_enabled(kind=VOD_KIND_MOVIE, user=user))
        self.assertTrue(is_vod_enabled(kind=VOD_KIND_SERIES, user=user))

        user = User(custom_properties={"vod_series_enabled": False})
        self.assertTrue(is_vod_enabled(kind=VOD_KIND_MOVIE, user=user))
        self.assertFalse(is_vod_enabled(kind=VOD_KIND_SERIES, user=user))

    def test_only_json_false_disables(self):
        """A truthy or missing value must not lock a user out by accident."""
        for value in (True, "false", 0, None):
            with self.subTest(value=value):
                user = User(custom_properties={"vod_movies_enabled": value})
                self.assertEqual(
                    is_vod_enabled(kind=VOD_KIND_MOVIE, user=user), value is not False
                )

    def test_no_user_is_not_restricted(self):
        self.assertTrue(is_vod_enabled(kind=VOD_KIND_MOVIE, user=None))

    def test_unknown_kind_is_a_programming_error(self):
        with self.assertRaises(ValueError):
            is_vod_enabled(kind="episode", user=None)


class VodKindForContentTypeTests(TestCase):
    def test_episodes_are_gated_by_the_series_flag(self):
        self.assertEqual(vod_kind_for_content_type("episode"), VOD_KIND_SERIES)
        self.assertEqual(vod_kind_for_content_type("series"), VOD_KIND_SERIES)

    def test_movies_map_to_the_movie_flag(self):
        self.assertEqual(vod_kind_for_content_type("movie"), VOD_KIND_MOVIE)

    def test_unknown_content_type_is_left_alone(self):
        self.assertIsNone(vod_kind_for_content_type("timeshift"))


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
