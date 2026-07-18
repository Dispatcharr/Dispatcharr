"""Security-focused tests for local logo path jailing and related helpers."""
import tempfile
import uuid
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.api_views import LogoViewSet
from apps.channels.models import Logo
from core.utils import resolve_safe_local_data_path, safe_upload_path


class ResolveSafeLocalDataPathTests(TestCase):
    def test_accepts_file_under_logos_root(self):
        name = f"_jail_test_{uuid.uuid4().hex}.png"
        target = Path("/data/logos") / name
        target.write_bytes(b"x")
        try:
            resolved = resolve_safe_local_data_path(
                str(target), allowed_roots=("/data/logos",)
            )
            self.assertEqual(resolved, str(target.resolve()))
        finally:
            target.unlink(missing_ok=True)

    def test_rejects_path_traversal_outside_root(self):
        self.assertIsNone(
            resolve_safe_local_data_path(
                "/data/../etc/passwd", allowed_roots=("/data/logos",)
            )
        )

    def test_rejects_non_data_prefix(self):
        self.assertIsNone(resolve_safe_local_data_path("/etc/passwd"))

    def test_safe_upload_path_strips_directory_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = safe_upload_path("../../evil.xml", tmp)
            self.assertEqual(Path(path).name, "evil.xml")
            self.assertTrue(Path(path).is_relative_to(Path(tmp).resolve()))


class LogoCachePathJailTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        User = get_user_model()
        self.user, _ = User.objects.get_or_create(
            username="logo_cache_admin",
            defaults={"user_level": User.UserLevel.ADMIN},
        )

    def test_traversal_url_returns_404(self):
        logo = Logo.objects.create(
            name="Traversal",
            url="/data/../etc/passwd",
        )
        request = self.factory.get(f"/api/channels/logos/{logo.id}/cache/")
        force_authenticate(request, user=self.user)
        view = LogoViewSet.as_view({"get": "cache"})
        response = view(request, pk=logo.id)
        self.assertEqual(response.status_code, 404)

    def test_valid_local_logo_is_served(self):
        name = f"_jail_serve_{uuid.uuid4().hex}.png"
        file_path = Path("/data/logos") / name
        file_path.write_bytes(b"\x89PNG\r\n\x1a\n")
        logo = Logo.objects.create(name="Ok", url=str(file_path))
        try:
            request = self.factory.get(f"/api/channels/logos/{logo.id}/cache/")
            view = LogoViewSet.as_view({"get": "cache"})
            response = view(request, pk=logo.id)
            self.assertEqual(response.status_code, 200)
            b"".join(response.streaming_content)
        finally:
            file_path.unlink(missing_ok=True)
