"""Tests for fail-closed XC credential transforms and shared URL building."""

from django.test import TestCase, SimpleTestCase
from unittest.mock import MagicMock, patch

from apps.channels.models import Stream
from apps.m3u.credentials import (
    build_xc_playback_url,
    get_transformed_credentials,
)
from apps.m3u.models import M3UAccount, M3UAccountProfile
from apps.proxy.live_proxy.url_utils import (
    _resolve_live_stream_url,
    get_stream_info_for_switch,
    transform_url,
)
from apps.proxy.vod_proxy.views import _build_vod_stream_url
from apps.vod.models import Episode, M3UEpisodeRelation, M3UMovieRelation, Movie, Series


class BuildXcPlaybackUrlTests(SimpleTestCase):
    def test_live_movie_series_shapes(self):
        self.assertEqual(
            build_xc_playback_url(
                "https://provider/base",
                "u",
                "p",
                content_path="live",
                stream_id="1",
                extension="ts",
            ),
            "https://provider/base/live/u/p/1.ts",
        )
        self.assertEqual(
            build_xc_playback_url(
                "https://provider/base/",
                "u",
                "p",
                content_path="movie",
                stream_id="9",
                extension="mkv",
            ),
            "https://provider/base/movie/u/p/9.mkv",
        )


class GetTransformedCredentialsFailClosedTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="cred-fail-closed",
            account_type="XC",
            server_url="http://provider.example",
            username="baseuser",
            password="basepass",
        )
        self.default = M3UAccountProfile.objects.get(
            m3u_account=self.account, is_default=True
        )

    def test_default_identity_pattern_keeps_base_credentials(self):
        server_url, username, password = get_transformed_credentials(
            self.account, self.default
        )
        self.assertEqual(server_url, "http://provider.example")
        self.assertEqual(username, "baseuser")
        self.assertEqual(password, "basepass")

    def test_matching_literal_pattern_rewrites_credentials(self):
        profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="user1",
            max_streams=1,
            is_active=True,
            search_pattern="baseuser/basepass",
            replace_pattern="user1/user1pass",
        )
        server_url, username, password = get_transformed_credentials(
            self.account, profile
        )
        self.assertEqual(server_url, "http://provider.example")
        self.assertEqual(username, "user1")
        self.assertEqual(password, "user1pass")

    def test_non_matching_pattern_returns_none_not_base(self):
        profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="stale-literal",
            max_streams=1,
            is_active=True,
            search_pattern="baseuser/oldpass",
            replace_pattern="user1/user1pass",
        )
        self.assertEqual(
            get_transformed_credentials(self.account, profile),
            (None, None, None),
        )

    def test_live_only_advanced_pattern_still_resolves_via_synthetic_url(self):
        """Live/catchup use a synthetic /live/.../1234.ts URL, so Live-only works."""
        profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="live-only",
            max_streams=1,
            is_active=True,
            search_pattern=r"(?<=/live/)[^/]+/[^/]+(?=/1234\.ts)",
            replace_pattern="user1/user1pass",
        )
        _url, username, password = get_transformed_credentials(self.account, profile)
        self.assertEqual(username, "user1")
        self.assertEqual(password, "user1pass")


class ResolveLiveStreamUrlFailClosedTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="live-resolve",
            account_type="XC",
            server_url="http://provider.example",
            username="baseuser",
            password="basepass",
        )
        self.stream = Stream.objects.create(
            name="Ch",
            m3u_account=self.account,
            stream_id="441305",
            url="http://provider.example/live/baseuser/basepass/441305.ts",
        )

    def test_xc_live_uses_transformed_credentials(self):
        profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="user1",
            max_streams=1,
            is_active=True,
            search_pattern="baseuser/basepass",
            replace_pattern="user1/user1pass",
        )
        url = _resolve_live_stream_url(self.stream, self.account, profile)
        self.assertEqual(
            url,
            "http://provider.example/live/user1/user1pass/441305.ts",
        )

    def test_xc_live_returns_none_when_transform_fails(self):
        profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="bad",
            max_streams=1,
            is_active=True,
            search_pattern="no/match",
            replace_pattern="user1/user1pass",
        )
        self.assertIsNone(
            _resolve_live_stream_url(self.stream, self.account, profile)
        )


class TransformUrlFailClosedTests(SimpleTestCase):
    def test_no_patterns_returns_original(self):
        url = "http://example.com/live/a/b/1.ts"
        self.assertEqual(transform_url(url, "", ""), url)
        self.assertEqual(transform_url(url, None, None), url)

    def test_matching_pattern_rewrites(self):
        self.assertEqual(
            transform_url(
                "http://example.com/live/user/pass/1.ts",
                r"(.*)/(.*)/(.*)/(.*)$",
                r"$1/newuser/newpass/$4",
            ),
            "http://example.com/live/newuser/newpass/1.ts",
        )

    def test_non_matching_pattern_returns_none(self):
        self.assertIsNone(
            transform_url(
                "http://example.com/movie/user/pass/1.mkv",
                r"(?<=/live/)[^/]+/[^/]+",
                "x/y",
            )
        )

    def test_timeout_returns_none_not_original(self):
        with patch(
            "apps.proxy.live_proxy.url_utils.regex.subn",
            side_effect=TimeoutError("regex timed out"),
        ):
            self.assertIsNone(transform_url("http://example.com/a", "a", "b"))


class GetStreamInfoForSwitchSlotReleaseTests(SimpleTestCase):
    """A credential transform failure must not leak a reserved connection slot."""

    @patch("apps.proxy.live_proxy.url_utils.close_old_connections")
    @patch("apps.proxy.live_proxy.url_utils._resolve_live_stream_url", return_value=None)
    @patch("apps.proxy.live_proxy.url_utils.get_object_or_404")
    def test_releases_slot_when_current_stream_credential_transform_fails(
        self, mock_get_404, _resolve, _close
    ):
        channel = MagicMock()
        channel.get_stream.return_value = (5, 7, None, True)  # slot_reserved=True
        stream = MagicMock(id=5, name="Ch")
        profile = MagicMock(id=7)
        mock_get_404.side_effect = [channel, stream, profile]

        result = get_stream_info_for_switch("channel-uuid")

        self.assertIn("error", result)
        channel.release_stream.assert_called_once()


class BuildVodStreamUrlTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="vod-creds",
            account_type="XC",
            server_url="http://provider.example",
            username="baseuser",
            password="basepass",
        )
        self.profile = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="user1",
            max_streams=1,
            is_active=True,
            search_pattern="baseuser/basepass",
            replace_pattern="user1/user1pass",
        )
        self.movie = Movie.objects.create(name="M")
        self.movie_rel = M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            stream_id="999",
            container_extension="mkv",
        )

    def test_vod_uses_same_transformed_credentials_as_live(self):
        url = _build_vod_stream_url(self.movie_rel, self.profile, "movie")
        self.assertEqual(
            url,
            "http://provider.example/movie/user1/user1pass/999.mkv",
        )

    def test_vod_returns_none_when_transform_fails(self):
        bad = M3UAccountProfile.objects.create(
            m3u_account=self.account,
            name="bad-vod",
            max_streams=1,
            is_active=True,
            search_pattern="stale/creds",
            replace_pattern="user1/user1pass",
        )
        self.assertIsNone(_build_vod_stream_url(self.movie_rel, bad, "movie"))

    def test_series_episode_path(self):
        series = Series.objects.create(name="S")
        episode = Episode.objects.create(
            series=series,
            name="E1",
            season_number=1,
            episode_number=1,
        )
        rel = M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=episode,
            stream_id="888",
            container_extension="mp4",
        )
        url = _build_vod_stream_url(rel, self.profile, "episode")
        self.assertEqual(
            url,
            "http://provider.example/series/user1/user1pass/888.mp4",
        )
