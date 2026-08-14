"""VOD proxy honors the global Redirect stream profile like live TV."""

from unittest.mock import MagicMock, patch

from django.http import HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.test import RequestFactory, SimpleTestCase


class StreamVodRedirectTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, path="/proxy/vod/movie/uuid/"):
        request = self.factory.get(path, HTTP_USER_AGENT="test-agent")
        request.user = MagicMock(is_authenticated=False)
        return request

    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    def test_stream_vod_redirects_without_session_mint(
        self,
        mock_manager_cls,
        _network_ok,
        _is_redirect,
        mock_select,
        _idle,
    ):
        mock_select.return_value = {
            "content_obj": MagicMock(),
            "m3u_account": MagicMock(),
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://provider.example/movie.mp4",
        }

        from apps.proxy.vod_proxy.views import stream_vod

        # No session_id and no idle match: redirect mode must skip the session-mint 301.
        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id="uuid",
            session_id=None,
        )

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response["Location"], "http://provider.example/movie.mp4")
        mock_select.assert_called_once()
        mock_manager_cls.get_instance.assert_not_called()

    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=False,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_stream_vod_proxies_when_not_redirect(
        self,
        _network_ok,
        _is_redirect,
        _idle,
        mock_select,
        mock_manager_cls,
        mock_close,
    ):
        movie = MagicMock()
        movie.name = "Test Movie"
        profile = MagicMock()
        profile.id = 1
        profile.max_streams = 5
        mock_select.return_value = {
            "content_obj": movie,
            "m3u_account": MagicMock(name="Provider"),
            "m3u_profile": profile,
            "current_connections": 0,
            "final_stream_url": "http://example.com/movie.mp4",
        }

        mock_manager = MagicMock()
        mock_manager.stream_content_with_session.return_value = StreamingHttpResponse(
            streaming_content=iter([b"data"]),
            content_type="video/mp4",
        )
        mock_manager_cls.get_instance.return_value = mock_manager

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request("/proxy/vod/movie/uuid/session123/"),
            content_type="movie",
            content_id="uuid",
            session_id="session123",
        )

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_manager.stream_content_with_session.assert_called_once()
        mock_close.assert_called_once()

    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream", return_value=None)
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_stream_vod_redirect_returns_503_when_no_url(
        self,
        _network_ok,
        _is_redirect,
        _select,
        _idle,
    ):
        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id="uuid",
            session_id=None,
        )

        self.assertEqual(response.status_code, 503)


    @patch("apps.proxy.vod_proxy.views.close_old_connections")
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_existing_session_proxies_even_when_default_is_redirect(
        self,
        _network_ok,
        _is_redirect,
        mock_select,
        mock_manager_cls,
        mock_close,
    ):
        """Redirect is decided on first request only; an established session keeps proxying."""
        movie = MagicMock()
        movie.name = "Test Movie"
        profile = MagicMock()
        profile.id = 1
        profile.max_streams = 5
        mock_select.return_value = {
            "content_obj": movie,
            "m3u_account": MagicMock(name="Provider"),
            "m3u_profile": profile,
            "current_connections": 0,
            "final_stream_url": "http://example.com/movie.mp4",
        }

        mock_manager = MagicMock()
        mock_manager.stream_content_with_session.return_value = StreamingHttpResponse(
            streaming_content=iter([b"data"]),
            content_type="video/mp4",
        )
        mock_manager_cls.get_instance.return_value = mock_manager

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request("/proxy/vod/movie/uuid/session123/"),
            content_type="movie",
            content_id="uuid",
            session_id="session123",
        )

        self.assertIsInstance(response, StreamingHttpResponse)
        mock_manager.stream_content_with_session.assert_called_once()
        # Redirect branch must not run when a session already exists.
        self.assertFalse(
            any(
                isinstance(c, HttpResponseRedirect)
                for c in [response]
            )
        )

    @patch("apps.proxy.vod_proxy.views._vod_session_path_redirect")
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "apps.proxy.vod_proxy.views._find_idle_vod_session",
        return_value="idle_session_abc",
    )
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_idle_session_match_skips_redirect(
        self,
        _network_ok,
        _is_redirect,
        mock_idle,
        mock_select,
        mock_path_redirect,
    ):
        """Idle fingerprint match (ip/user-agent/content, same check the
        connection manager already uses for reconnects) wins over Redirect
        and adopts that session directly instead of hopping to the provider."""
        expected = HttpResponse(
            status=301, headers={"Location": "/proxy/vod/movie/uuid/idle_session_abc"}
        )
        mock_path_redirect.return_value = expected

        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id="uuid",
            session_id=None,
        )

        self.assertIs(response, expected)
        mock_idle.assert_called_once()
        mock_select.assert_not_called()
        mock_path_redirect.assert_called_once()
        self.assertEqual(mock_path_redirect.call_args.args[1], "idle_session_abc")

    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=False,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_no_idle_check_when_not_redirect(
        self,
        _network_ok,
        _is_redirect,
        mock_idle,
        mock_select,
    ):
        """Proxy-mode installs never pay for the idle-session scan; the mint
        path is unchanged from before Redirect existed."""
        from apps.proxy.vod_proxy.views import stream_vod

        response = stream_vod(
            self._request(),
            content_type="movie",
            content_id="uuid",
            session_id=None,
        )

        self.assertEqual(response.status_code, 301)
        mock_idle.assert_not_called()
        mock_select.assert_not_called()


class HeadVodRedirectTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    @patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager")
    def test_head_vod_redirects_to_provider(
        self,
        mock_manager_cls,
        _network_ok,
        _is_redirect,
        mock_select,
        _idle,
    ):
        mock_select.return_value = {
            "final_stream_url": "http://provider.example/movie.mp4",
        }

        request = self.factory.head(
            "/proxy/vod/movie/uuid/",
            HTTP_USER_AGENT="test-agent",
        )

        from apps.proxy.vod_proxy.views import head_vod

        response = head_vod(request, content_type="movie", content_id="uuid")

        self.assertIsInstance(response, HttpResponseRedirect)
        self.assertEqual(response["Location"], "http://provider.example/movie.mp4")
        mock_select.assert_called_once()
        mock_manager_cls.get_instance.assert_not_called()

    @patch("apps.proxy.vod_proxy.views._select_vod_stream")
    @patch(
        "apps.proxy.vod_proxy.views._find_idle_vod_session",
        return_value="idle_session_abc",
    )
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=True,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_head_vod_adopts_idle_session(
        self,
        _network_ok,
        _is_redirect,
        mock_idle,
        mock_select,
    ):
        """An idle fingerprint match adopts that session_id directly instead
        of redirecting to the provider or minting a new one."""
        movie = MagicMock()
        movie.name = "Test Movie"
        m3u_account = MagicMock(name="Provider")
        m3u_account.get_user_agent_string.return_value = "test-agent"
        mock_select.return_value = {
            "content_obj": movie,
            "m3u_account": m3u_account,
            "m3u_profile": MagicMock(),
            "current_connections": 0,
            "final_stream_url": "http://example.com/movie.mp4",
        }

        request = self.factory.head(
            "/proxy/vod/movie/uuid/",
            HTTP_USER_AGENT="test-agent",
        )

        provider_response = MagicMock()
        provider_response.status_code = 200
        provider_response.headers = {"Content-Length": "1234", "Content-Type": "video/mp4"}

        with patch("apps.proxy.vod_proxy.views.requests.get", return_value=provider_response), \
             patch("apps.proxy.vod_proxy.views.MultiWorkerVODConnectionManager"):
            from apps.proxy.vod_proxy.views import head_vod

            response = head_vod(request, content_type="movie", content_id="uuid")

        mock_idle.assert_called_once()
        self.assertEqual(response["X-Dispatcharr-Session"], "idle_session_abc")
        self.assertIn("idle_session_abc", response["X-Session-URL"])
        # _select_vod_stream is called once, using the adopted session_id
        # (not for the redirect-decision path, since a match was found).
        mock_select.assert_called_once()
        self.assertEqual(mock_select.call_args.args[-1], "idle_session_abc")

    @patch("apps.proxy.vod_proxy.views._find_idle_vod_session", return_value=None)
    @patch("apps.proxy.vod_proxy.views._select_vod_stream", return_value=None)
    @patch(
        "core.models.CoreSettings.is_default_stream_profile_redirect",
        return_value=False,
    )
    @patch("apps.proxy.vod_proxy.views.network_access_allowed", return_value=True)
    def test_head_vod_no_idle_check_when_not_redirect(
        self,
        _network_ok,
        _is_redirect,
        mock_select,
        mock_idle,
    ):
        """Proxy-mode HEAD requests never pay for the idle-session scan; the
        mint path is taken directly and falls through to normal profile
        selection (503 here, since _select_vod_stream is stubbed to None)."""
        request = self.factory.head(
            "/proxy/vod/movie/uuid/",
            HTTP_USER_AGENT="test-agent",
        )

        from apps.proxy.vod_proxy.views import head_vod

        response = head_vod(request, content_type="movie", content_id="uuid")

        mock_idle.assert_not_called()
        self.assertEqual(response.status_code, 503)


class SelectVodStreamTests(SimpleTestCase):
    @patch(
        "apps.proxy.vod_proxy.views._transform_url",
        return_value="http://final/movie.mp4",
    )
    @patch("apps.proxy.vod_proxy.views._get_m3u_profile")
    @patch(
        "apps.proxy.vod_proxy.views._get_stream_url_from_relation",
        return_value="http://upstream/movie.mp4",
    )
    @patch("apps.proxy.vod_proxy.views._get_content_and_relation")
    def test_select_returns_provider_url(
        self,
        mock_content,
        _stream_url,
        mock_profile,
        _transform,
    ):
        relation = MagicMock()
        relation.m3u_account.name = "Provider"
        relation.m3u_account.priority = 10
        movie = MagicMock()
        mock_content.return_value = (movie, relation, [relation])
        profile = MagicMock()
        mock_profile.return_value = (profile, 0)

        from apps.proxy.vod_proxy.views import _select_vod_stream

        selected = _select_vod_stream("movie", "uuid")

        self.assertEqual(selected["final_stream_url"], "http://final/movie.mp4")
        self.assertNotIn("user_agent", selected)
        mock_profile.assert_called_once()
