from unittest.mock import patch, MagicMock
from django.test import TestCase
from apps.m3u.models import M3UAccount
from apps.vod.models import Movie, Series, Episode, VODLogo, M3UMovieRelation, M3USeriesRelation, M3UEpisodeRelation
from apps.vod.image_proxy import (
    is_proxyable_image_url,
    prefer_relation_artwork,
    resolve_vod_image_url,
    rewrite_backdrop_paths,
    rewrite_single_image_url,
    vod_image_url_parts,
    format_vod_image_url,
)


class VODImageProxyHelpersTestCase(TestCase):
    def test_is_proxyable_image_url(self):
        self.assertTrue(is_proxyable_image_url("http://example.com/a.jpg"))
        self.assertTrue(is_proxyable_image_url("https://cdn.example.com/b.png"))
        self.assertTrue(is_proxyable_image_url("/data/logos/local.png"))
        self.assertFalse(is_proxyable_image_url("/img1.jpg"))
        self.assertFalse(is_proxyable_image_url(""))
        self.assertFalse(is_proxyable_image_url(None))

    def test_resolve_backdrop_by_index(self):
        movie = Movie(
            name="Test",
            custom_properties={
                "backdrop_path": [
                    "https://cdn.example.com/a.jpg",
                    "https://cdn.example.com/b.jpg",
                ]
            },
        )
        self.assertEqual(
            resolve_vod_image_url(movie, "backdrop", 0),
            "https://cdn.example.com/a.jpg",
        )
        self.assertEqual(
            resolve_vod_image_url(movie, "backdrop", 1),
            "https://cdn.example.com/b.jpg",
        )
        self.assertIsNone(resolve_vod_image_url(movie, "backdrop", 2))
        self.assertIsNone(resolve_vod_image_url(movie, "unknown", 0))

    def test_resolve_movie_image(self):
        episode = Episode(
            name="Pilot",
            custom_properties={"movie_image": "https://cdn.example.com/still.jpg"},
        )
        self.assertEqual(
            resolve_vod_image_url(episode, "movie_image"),
            "https://cdn.example.com/still.jpg",
        )

    def test_resolve_skips_non_proxyable_urls(self):
        movie = Movie(
            name="Test",
            custom_properties={"backdrop_path": ["/relative.jpg"]},
        )
        self.assertIsNone(resolve_vod_image_url(movie, "backdrop", 0))

    def test_rewrite_backdrop_paths_proxies_absolute_only(self):
        rewritten = rewrite_backdrop_paths(
            None,
            "movie",
            42,
            ["https://cdn.example.com/a.jpg", "/relative.jpg", ""],
        )
        self.assertEqual(len(rewritten), 3)
        self.assertIn("/api/vod/movies/42/image/", rewritten[0])
        self.assertIn("kind=backdrop", rewritten[0])
        self.assertIn("index=0", rewritten[0])
        self.assertEqual(rewritten[1], "/relative.jpg")
        self.assertEqual(rewritten[2], "")

    def test_rewrite_with_precomputed_url_parts_avoids_per_row_reverse(self):
        parts = vod_image_url_parts(None, "series")
        a = rewrite_backdrop_paths(
            None,
            "series",
            10,
            ["https://cdn.example.com/a.jpg"],
            url_parts=parts,
        )
        b = format_vod_image_url(
            parts[0], parts[1], 10, "backdrop", index=0, source_url="https://cdn.example.com/a.jpg"
        )
        self.assertEqual(a[0], b)
        self.assertIn("/api/vod/series/10/image/", a[0])

    def test_rewrite_single_image_url(self):
        proxied = rewrite_single_image_url(
            None, "episode", 7, "movie_image", "https://cdn.example.com/still.jpg"
        )
        self.assertIn("/api/vod/episodes/7/image/", proxied)
        self.assertIn("kind=movie_image", proxied)
        self.assertEqual(
            rewrite_single_image_url(None, "episode", 7, "movie_image", "/rel.jpg"),
            "/rel.jpg",
        )

    def test_rewrite_includes_m3u_account_id(self):
        proxied = rewrite_single_image_url(
            None,
            "episode",
            7,
            "movie_image",
            "https://cdn.example.com/still.jpg",
            m3u_account_id=99,
        )
        self.assertIn("m3u_account_id=99", proxied)

    def test_prefer_relation_artwork_falls_back_to_object(self):
        art = prefer_relation_artwork(
            {"info": {"info": {}}},
            {"movie_image": "https://cdn.example.com/object.jpg"},
        )
        self.assertEqual(art["movie_image"], "https://cdn.example.com/object.jpg")

    def test_prefer_relation_artwork_from_episode_info(self):
        art = prefer_relation_artwork(
            {
                "info": {
                    "info": {
                        "movie_image": "https://cdn.example.com/relation.jpg",
                    }
                }
            },
            {"movie_image": "https://cdn.example.com/stale.jpg"},
        )
        self.assertEqual(art["movie_image"], "https://cdn.example.com/relation.jpg")

    def test_relation_artwork_from_basic_data_stream_icon(self):
        # Every movie/series relation stores the raw list-sync payload under
        # basic_data, refreshed on every sync even without an advanced fetch.
        art = prefer_relation_artwork(
            {"basic_data": {"stream_icon": "https://cdn.example.com/icon.jpg"}},
            {},
        )
        self.assertEqual(art["movie_image"], "https://cdn.example.com/icon.jpg")

    def test_relation_artwork_from_basic_data_cover(self):
        art = prefer_relation_artwork(
            {"basic_data": {"cover": "https://cdn.example.com/cover.jpg"}},
            {},
        )
        self.assertEqual(art["movie_image"], "https://cdn.example.com/cover.jpg")

    def test_relation_artwork_from_basic_data_backdrop(self):
        art = prefer_relation_artwork(
            {"basic_data": {"backdrop_path": "https://cdn.example.com/bd.jpg"}},
            {"backdrop_path": ["https://cdn.example.com/stale-bd.jpg"]},
        )
        self.assertEqual(art["backdrop_path"], ["https://cdn.example.com/bd.jpg"])

    def test_detailed_info_takes_priority_over_basic_data(self):
        art = prefer_relation_artwork(
            {
                "detailed_info": {"movie_image": "https://cdn.example.com/detailed.jpg"},
                "basic_data": {"stream_icon": "https://cdn.example.com/icon.jpg"},
            },
            {},
        )
        self.assertEqual(art["movie_image"], "https://cdn.example.com/detailed.jpg")


class VODImageProxyEndpointTestCase(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="VOD Image Account",
            server_url="http://provider.example.com",
            username="user",
            password="pass",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=1,
        )
        self.logo = VODLogo.objects.create(
            name="Poster",
            url="https://cdn.example.com/poster.jpg",
        )
        self.movie = Movie.objects.create(
            name="Proxy Movie",
            logo=self.logo,
            custom_properties={
                "backdrop_path": ["https://cdn.example.com/backdrop.jpg"],
            },
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.movie,
            stream_id="m1",
        )
        self.series = Series.objects.create(
            name="Proxy Series",
            logo=self.logo,
            custom_properties={
                "backdrop_path": ["https://cdn.example.com/series-bd.jpg"],
            },
        )
        M3USeriesRelation.objects.create(
            m3u_account=self.account,
            series=self.series,
            external_series_id="s1",
        )
        self.episode = Episode.objects.create(
            name="Pilot",
            series=self.series,
            season_number=1,
            episode_number=1,
            custom_properties={
                "movie_image": "https://cdn.example.com/still.jpg",
            },
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=self.account,
            episode=self.episode,
            stream_id="e1",
        )

    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_movie_backdrop_image_endpoint(self, _mock_ua, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"backdrop-bytes"]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(
            f"/api/vod/movies/{self.movie.id}/image/?kind=backdrop&index=0"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"backdrop-bytes")
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://cdn.example.com/backdrop.jpg")
        self.assertEqual(
            kwargs.get("headers"),
            {"User-Agent": "Dispatcharr-Test/1.0"},
        )

    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_episode_movie_image_endpoint(self, _mock_ua, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"still-bytes"]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(
            f"/api/vod/episodes/{self.episode.id}/image/?kind=movie_image"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"still-bytes")

    def test_rejects_unknown_kind(self):
        response = self.client.get(
            f"/api/vod/movies/{self.movie.id}/image/?kind=not-a-kind"
        )
        self.assertEqual(response.status_code, 404)

    def test_missing_backdrop_index_returns_404(self):
        response = self.client.get(
            f"/api/vod/movies/{self.movie.id}/image/?kind=backdrop&index=9"
        )
        self.assertEqual(response.status_code, 404)

    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_series_backdrop_image_endpoint(self, _mock_ua, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"series-bd"]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(
            f"/api/vod/series/{self.series.id}/image/?kind=backdrop&index=0"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"series-bd")

    @patch("core.image_proxy.requests.get")
    @patch(
        "core.image_proxy.CoreSettings.get_default_user_agent",
        return_value="Dispatcharr-Test/1.0",
    )
    def test_resolve_prefers_higher_priority_relation_artwork(self, _mock_ua, mock_get):
        high = M3UAccount.objects.create(
            name="High Priority",
            server_url="http://high.example.com",
            username="h",
            password="h",
            account_type=M3UAccount.Types.XC,
            is_active=True,
            priority=50,
        )
        # Shared object has a stale still; lower-priority account wrote it later.
        self.episode.custom_properties = {
            "movie_image": "https://cdn.example.com/stale.jpg",
        }
        self.episode.save(update_fields=["custom_properties"])
        M3UEpisodeRelation.objects.filter(episode=self.episode, m3u_account=self.account).update(
            custom_properties={
                "info": {
                    "info": {"movie_image": "https://cdn.example.com/low.jpg"},
                }
            }
        )
        M3UEpisodeRelation.objects.create(
            m3u_account=high,
            episode=self.episode,
            stream_id="e-high",
            custom_properties={
                "info": {
                    "info": {"movie_image": "https://cdn.example.com/high.jpg"},
                }
            },
        )

        self.assertEqual(
            resolve_vod_image_url(self.episode, "movie_image"),
            "https://cdn.example.com/high.jpg",
        )
        self.assertEqual(
            resolve_vod_image_url(
                self.episode, "movie_image", m3u_account_id=self.account.id
            ),
            "https://cdn.example.com/low.jpg",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_content.return_value = [b"high-still"]
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_get.return_value = mock_response

        response = self.client.get(
            f"/api/vod/episodes/{self.episode.id}/image/?kind=movie_image"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"high-still")
        self.assertEqual(mock_get.call_args[0][0], "https://cdn.example.com/high.jpg")
