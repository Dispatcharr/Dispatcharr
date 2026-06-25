"""Tests for XC stream URL normalization and on-demand URL building."""

from django.test import TestCase

from apps.channels.models import Stream
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.m3u.tasks import get_transformed_credentials
from apps.proxy.live_proxy.url_utils import _resolve_live_stream_url
from apps.vod.models import Episode, M3UEpisodeRelation, M3UMovieRelation, Movie, Series
from core.xtream_codes import normalize_server_url


class NormalizeServerUrlTests(TestCase):
    def test_preserves_sub_path(self):
        url = "https://myserver.fun/server1"
        self.assertEqual(normalize_server_url(url), "https://myserver.fun/server1")

    def test_strips_player_api_php_and_query_params(self):
        url = "https://myserver.fun/server1/player_api.php?username=foo&password=bar"
        self.assertEqual(normalize_server_url(url), "https://myserver.fun/server1")

    def test_strips_trailing_slash(self):
        url = "https://myserver.fun/server1/"
        self.assertEqual(normalize_server_url(url), "https://myserver.fun/server1")

    def test_nested_sub_path_with_php_endpoint(self):
        url = "http://server/Pluto/gb/player_api.php"
        self.assertEqual(normalize_server_url(url), "http://server/Pluto/gb")


class GetTransformedCredentialsTests(TestCase):
    def test_returns_normalized_server_url(self):
        account = M3UAccount.objects.create(
            name="Sub-path XC",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

        server_url, username, password = get_transformed_credentials(account, profile)

        self.assertEqual(server_url, "https://myserver.fun/server1")
        self.assertEqual(username, "alice")
        self.assertEqual(password, "secret")


class ResolveLiveStreamUrlTests(TestCase):
    def test_builds_url_from_normalized_base_not_raw_account_url(self):
        account = M3UAccount.objects.create(
            name="Live sub-path",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name="Test Channel",
            m3u_account=account,
            stream_id="12345",
            url="https://myserver.fun/server1/live/olduser/oldpass/12345.ts",
        )

        url = _resolve_live_stream_url(stream, account, profile)

        self.assertEqual(
            url,
            "https://myserver.fun/server1/live/alice/secret/12345.ts",
        )

    def test_std_account_uses_stored_stream_url(self):
        account = M3UAccount.objects.create(
            name="STD account",
            account_type="STD",
            server_url="https://example.com/list.m3u",
            username="alice",
            password="secret",
        )
        profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
        stream = Stream.objects.create(
            name="STD Stream",
            m3u_account=account,
            url="https://provider.example/stream/abc123",
        )

        url = _resolve_live_stream_url(stream, account, profile)

        self.assertEqual(url, "https://provider.example/stream/abc123")


class VodStreamUrlTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="VOD sub-path",
            account_type="XC",
            server_url="https://myserver.fun/server1/player_api.php?username=foo",
            username="alice",
            password="secret",
        )

    def test_movie_relation_builds_normalized_url(self):
        movie = Movie.objects.create(name="Test Movie")
        relation = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=movie,
            stream_id="999",
            container_extension="mkv",
        )

        url = relation.get_stream_url()

        self.assertEqual(
            url,
            "https://myserver.fun/server1/movie/alice/secret/999.mkv",
        )

    def test_episode_relation_builds_normalized_url(self):
        series = Series.objects.create(name="Test Series")
        episode = Episode.objects.create(
            series=series,
            name="Pilot",
            season_number=1,
            episode_number=1,
        )
        relation = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            stream_id="888",
            container_extension="mp4",
        )

        url = relation.get_stream_url()

        self.assertEqual(
            url,
            "https://myserver.fun/server1/series/alice/secret/888.mp4",
        )
