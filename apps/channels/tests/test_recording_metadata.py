"""Tests for recording metadata endpoints and logo proxy negative cache.

Covers:
  - update_metadata endpoint: title/description, user_edited flag, validation
  - refresh_artwork endpoint: returns immediately, background thread behavior
  - Logo proxy negative cache: cache hit/miss, expiry, eviction, success clears
"""
import time as time_mod
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording, Logo
from apps.channels.api_views import RecordingViewSet, LogoViewSet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_admin():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u, _ = User.objects.get_or_create(
        username="metadata_test_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    u.set_password("pass")
    u.save()
    return u


# ---------------------------------------------------------------------------
# update_metadata endpoint
# ---------------------------------------------------------------------------

class UpdateMetadataTests(TestCase):
    """Tests for POST /api/channels/recordings/{id}/update-metadata/"""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=70, name="Meta Test Channel")
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _update(self, rec, data):
        request = self.factory.post(
            f"/api/channels/recordings/{rec.id}/update-metadata/",
            data, format="json",
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "update_metadata"})
        return view(request, pk=rec.id)

    def _make_rec(self, custom_properties=None):
        now = timezone.now()
        return Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties=custom_properties or {},
        )

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_update_title_only(self, _ws):
        rec = self._make_rec()
        response = self._update(rec, {"title": "My Show"})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        program = rec.custom_properties["program"]
        self.assertEqual(program["title"], "My Show")
        self.assertTrue(program["user_edited"])

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_update_description_only(self, _ws):
        rec = self._make_rec({"program": {"title": "Existing Title"}})
        response = self._update(rec, {"description": "A great episode"})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        program = rec.custom_properties["program"]
        self.assertEqual(program["description"], "A great episode")
        self.assertEqual(program["title"], "Existing Title")
        self.assertTrue(program["user_edited"])

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_update_both_fields(self, _ws):
        rec = self._make_rec()
        response = self._update(rec, {"title": "New Title", "description": "New Desc"})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        program = rec.custom_properties["program"]
        self.assertEqual(program["title"], "New Title")
        self.assertEqual(program["description"], "New Desc")
        self.assertTrue(program["user_edited"])

    def test_no_fields_returns_400(self):
        rec = self._make_rec()
        response = self._update(rec, {})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_whitespace_trimmed(self, _ws):
        rec = self._make_rec()
        response = self._update(rec, {"title": "  Padded Title  "})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties["program"]["title"], "Padded Title")

    def test_whitespace_only_title_returns_400(self):
        """Whitespace-only title and description should be rejected."""
        rec = self._make_rec()
        response = self._update(rec, {"title": "   ", "description": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.data.get("success"))

    def test_whitespace_only_title_with_valid_description(self):
        """Whitespace-only title is ignored; valid description is accepted."""
        rec = self._make_rec({"program": {"title": "Original"}})
        with patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None):
            response = self._update(rec, {"title": "   ", "description": "Valid desc"})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        # Title should remain unchanged since the whitespace-only value is not applied
        self.assertEqual(rec.custom_properties["program"]["title"], "Original")
        self.assertEqual(rec.custom_properties["program"]["description"], "Valid desc")

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_creates_program_dict_when_absent(self, _ws):
        """Recording with no program dict gets one created."""
        rec = self._make_rec({"status": "completed"})
        response = self._update(rec, {"title": "Brand New"})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        self.assertIn("program", rec.custom_properties)
        self.assertEqual(rec.custom_properties["program"]["title"], "Brand New")

    def test_returns_404_for_nonexistent(self):
        request = self.factory.post(
            "/api/channels/recordings/99999/update-metadata/",
            {"title": "Ghost"}, format="json",
        )
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "update_metadata"})
        self.assertEqual(view(request, pk=99999).status_code, 404)

    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_sends_websocket_event(self, mock_ws):
        rec = self._make_rec()
        self._update(rec, {"title": "WS Test"})
        mock_ws.assert_called_once()
        payload = mock_ws.call_args[0][2]
        self.assertEqual(payload["type"], "recording_updated")
        self.assertEqual(payload["recording_id"], rec.id)

    @patch("core.utils.send_websocket_update", side_effect=Exception("WS down"))
    def test_ws_failure_does_not_fail_request(self, _ws):
        """WebSocket errors are silenced — the save still succeeds."""
        rec = self._make_rec()
        response = self._update(rec, {"title": "Resilient"})
        self.assertEqual(response.status_code, 200)
        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties["program"]["title"], "Resilient")


# ---------------------------------------------------------------------------
# refresh_artwork endpoint
# ---------------------------------------------------------------------------

class RefreshArtworkTests(TestCase):
    """Tests for POST /api/channels/recordings/{id}/refresh-artwork/"""

    def setUp(self):
        self.channel = Channel.objects.create(channel_number=71, name="Artwork Test Channel")
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _refresh(self, rec):
        request = self.factory.post(f"/api/channels/recordings/{rec.id}/refresh-artwork/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "refresh_artwork"})
        return view(request, pk=rec.id)

    def _make_rec(self, custom_properties=None):
        now = timezone.now()
        return Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties=custom_properties or {},
        )

    @patch("threading.Thread")
    def test_returns_200_immediately(self, mock_thread):
        mock_thread.return_value.start = MagicMock()
        rec = self._make_rec()
        response = self._refresh(rec)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.get("success"))

    @patch("threading.Thread")
    def test_spawns_background_thread(self, mock_thread):
        mock_thread.return_value.start = MagicMock()
        rec = self._make_rec()
        self._refresh(rec)
        mock_thread.assert_called_once()
        self.assertTrue(mock_thread.call_args[1].get("daemon", False))
        mock_thread.return_value.start.assert_called_once()

    def test_returns_404_for_nonexistent(self):
        request = self.factory.post("/api/channels/recordings/99999/refresh-artwork/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "refresh_artwork"})
        self.assertEqual(view(request, pk=99999).status_code, 404)

    @patch("django.db.close_old_connections")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_no_downgrade_to_channel_logo(self, _ws, _close):
        """When the pipeline returns the channel's own logo, existing poster is preserved."""
        logo = Logo.objects.create(name="Channel Logo", url="https://example.com/ch.png")
        self.channel.logo = logo
        self.channel.save()
        rec = self._make_rec({
            "poster_logo_id": 999,  # existing real poster
            "poster_url": "https://tmdb.com/real-poster.jpg",
        })

        with patch("apps.channels.tasks._resolve_poster_for_program",
                    return_value=(logo.id, None)):
            request = self.factory.post(f"/api/channels/recordings/{rec.id}/refresh-artwork/")
            force_authenticate(request, user=self.user)

            # Run synchronously by intercepting the thread
            captured_fn = None
            def capture_thread(*args, **kwargs):
                nonlocal captured_fn
                captured_fn = kwargs.get("target") or args[0]
                mock = MagicMock()
                mock.start = lambda: captured_fn(*kwargs.get("args", ()))
                return mock

            with patch("threading.Thread", side_effect=capture_thread):
                view = RecordingViewSet.as_view({"post": "refresh_artwork"})
                view(request, pk=rec.id)

        rec.refresh_from_db()
        # Existing poster should be preserved — not downgraded to channel logo
        self.assertEqual(rec.custom_properties.get("poster_logo_id"), 999)
        self.assertEqual(rec.custom_properties.get("poster_url"), "https://tmdb.com/real-poster.jpg")

    @patch("django.db.close_old_connections")
    @patch("core.utils.send_websocket_update", side_effect=lambda *a, **kw: None)
    def test_upgrade_from_no_poster(self, _ws, _close):
        """When a recording has no poster and the pipeline finds one, it gets updated."""
        rec = self._make_rec({"program": {"title": "Some Show", "id": 42}})

        with patch("apps.channels.tasks._resolve_poster_for_program",
                    return_value=(555, "https://tmdb.com/new-poster.jpg")):
            captured_fn = None
            def capture_thread(*args, **kwargs):
                nonlocal captured_fn
                captured_fn = kwargs.get("target") or args[0]
                mock = MagicMock()
                mock.start = lambda: captured_fn(*kwargs.get("args", ()))
                return mock

            with patch("threading.Thread", side_effect=capture_thread):
                request = self.factory.post(f"/api/channels/recordings/{rec.id}/refresh-artwork/")
                force_authenticate(request, user=self.user)
                view = RecordingViewSet.as_view({"post": "refresh_artwork"})
                view(request, pk=rec.id)

        rec.refresh_from_db()
        self.assertEqual(rec.custom_properties.get("poster_logo_id"), 555)
        self.assertEqual(rec.custom_properties.get("poster_url"), "https://tmdb.com/new-poster.jpg")


# ---------------------------------------------------------------------------
# Logo proxy negative cache
# ---------------------------------------------------------------------------

class LogoNegativeCacheTests(TestCase):
    """Tests for the _logo_fetch_failures negative cache in LogoViewSet.cache()."""

    def setUp(self):
        from apps.channels import api_views
        self._failures = api_views._logo_fetch_failures
        self._failures.clear()
        self.factory = APIRequestFactory()
        self.user = _make_admin()

    def _fetch_logo(self, logo):
        request = self.factory.get(f"/api/channels/logos/{logo.id}/cache/")
        force_authenticate(request, user=self.user)
        view = LogoViewSet.as_view({"get": "cache"})
        return view(request, pk=logo.id)

    def test_failed_url_cached_on_non_200(self):
        """Non-200 response adds URL to negative cache."""
        logo = Logo.objects.create(name="Dead Logo", url="https://dead-cdn.com/logo.png")
        mock_resp = MagicMock(status_code=404)
        with patch("apps.channels.api_views.requests.get", return_value=mock_resp), \
             patch("apps.channels.api_views.CoreSettings.get_default_user_agent_id", return_value="1"), \
             patch("apps.channels.api_views.UserAgent.objects.get", return_value=MagicMock(user_agent="Test/1.0")):
            response = self._fetch_logo(logo)
        self.assertEqual(response.status_code, 404)
        self.assertIn("https://dead-cdn.com/logo.png", self._failures)

    def test_cached_failure_returns_404_immediately(self):
        """Subsequent request for a cached-failed URL returns 404 without making a request."""
        logo = Logo.objects.create(name="Cached Fail", url="https://cached-fail.com/logo.png")
        self._failures["https://cached-fail.com/logo.png"] = time_mod.monotonic() + 300

        with patch("apps.channels.api_views.requests.get") as mock_get:
            response = self._fetch_logo(logo)
        self.assertEqual(response.status_code, 404)
        mock_get.assert_not_called()

    def test_expired_cache_entry_allows_retry(self):
        """After TTL expires, a new request is made."""
        logo = Logo.objects.create(name="Expired", url="https://expired.com/logo.png")
        self._failures["https://expired.com/logo.png"] = time_mod.monotonic() - 1  # already expired

        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.iter_content = MagicMock(return_value=[b"img"])
        with patch("apps.channels.api_views.requests.get", return_value=mock_resp), \
             patch("apps.channels.api_views.CoreSettings.get_default_user_agent_id", return_value="1"), \
             patch("apps.channels.api_views.UserAgent.objects.get", return_value=MagicMock(user_agent="Test/1.0")):
            response = self._fetch_logo(logo)
        self.assertEqual(response.status_code, 200)

    def test_success_clears_previous_failure(self):
        """A successful fetch removes the URL from the failure cache."""
        url = "https://recovered.com/logo.png"
        logo = Logo.objects.create(name="Recovered", url=url)
        self._failures[url] = time_mod.monotonic() - 1  # expired

        mock_resp = MagicMock(status_code=200)
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.iter_content = MagicMock(return_value=[b"img"])
        with patch("apps.channels.api_views.requests.get", return_value=mock_resp), \
             patch("apps.channels.api_views.CoreSettings.get_default_user_agent_id", return_value="1"), \
             patch("apps.channels.api_views.UserAgent.objects.get", return_value=MagicMock(user_agent="Test/1.0")):
            self._fetch_logo(logo)
        self.assertNotIn(url, self._failures)

    def test_request_exception_cached(self):
        """Network errors are cached the same as non-200 responses."""
        import requests
        logo = Logo.objects.create(name="Timeout", url="https://timeout.com/logo.png")
        with patch("apps.channels.api_views.requests.get", side_effect=requests.Timeout("timed out")), \
             patch("apps.channels.api_views.CoreSettings.get_default_user_agent_id", return_value="1"), \
             patch("apps.channels.api_views.UserAgent.objects.get", return_value=MagicMock(user_agent="Test/1.0")):
            response = self._fetch_logo(logo)
        self.assertEqual(response.status_code, 404)
        self.assertIn("https://timeout.com/logo.png", self._failures)

    def test_eviction_when_cache_exceeds_256(self):
        """Stale entries are evicted when the cache grows past 256."""
        now = time_mod.monotonic()
        # Fill with 257 expired entries
        for i in range(257):
            self._failures[f"https://old-{i}.com/x.png"] = now - 1  # already expired

        logo = Logo.objects.create(name="Trigger", url="https://trigger-evict.com/logo.png")
        import requests
        with patch("apps.channels.api_views.requests.get", side_effect=requests.ConnectionError("fail")), \
             patch("apps.channels.api_views.CoreSettings.get_default_user_agent_id", return_value="1"), \
             patch("apps.channels.api_views.UserAgent.objects.get", return_value=MagicMock(user_agent="Test/1.0")):
            self._fetch_logo(logo)

        # Expired entries should be evicted
        old_entries = [k for k in self._failures if k.startswith("https://old-")]
        self.assertEqual(len(old_entries), 0)
        # New failure entry should exist
        self.assertIn("https://trigger-evict.com/logo.png", self._failures)
