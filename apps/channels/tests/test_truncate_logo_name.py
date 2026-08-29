from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.channels.models import Logo
from apps.channels.serializers import LogoSerializer
from apps.channels.tasks import _resolve_poster_for_program
from apps.vod.models import VODLogo
from apps.vod.serializers import VODLogoSerializer
from core.utils import truncate_with_warning


def _logo_name_max_length():
    return Logo._meta.get_field("name").max_length


class TruncateWithWarningHelperTests(TestCase):
    def test_short_value_unchanged(self):
        self.assertEqual(
            truncate_with_warning(
                "CNN",
                max_length=_logo_name_max_length(),
                label="Logo name",
            ),
            "CNN",
        )

    def test_exact_limit_unchanged(self):
        max_length = _logo_name_max_length()
        name = "x" * max_length
        self.assertEqual(
            truncate_with_warning(name, max_length=max_length, label="Logo name"),
            name,
        )

    def test_long_value_truncated(self):
        max_length = _logo_name_max_length()
        name = "a" * (max_length + 50)
        result = truncate_with_warning(
            name, max_length=max_length, label="Logo name"
        )
        self.assertEqual(len(result), max_length)
        self.assertEqual(result, name[:max_length])

    def test_none_passthrough(self):
        self.assertIsNone(
            truncate_with_warning(
                None,
                max_length=_logo_name_max_length(),
                label="Logo name",
            )
        )

    def test_custom_max_length(self):
        self.assertEqual(
            truncate_with_warning("abcdef", max_length=3, label="Logo name"),
            "abc",
        )


class LogoNameTruncationModelTests(TestCase):
    def test_create_truncates_long_name(self):
        max_length = _logo_name_max_length()
        long_name = "provider-title-" + ("x" * 400)
        logo = Logo.objects.create(
            name=long_name,
            url="https://example.com/logo-create.png",
        )
        logo.refresh_from_db()
        self.assertEqual(len(logo.name), max_length)
        self.assertEqual(logo.name, long_name[:max_length])

    def test_get_or_create_truncates_long_name(self):
        max_length = _logo_name_max_length()
        long_name = "y" * 300
        logo, created = Logo.objects.get_or_create(
            url="https://example.com/logo-goc.png",
            defaults={"name": long_name},
        )
        self.assertTrue(created)
        logo.refresh_from_db()
        self.assertEqual(logo.name, long_name[:max_length])

    def test_bulk_create_truncates_long_names(self):
        # Mirrors bulk channel creation / EPG logo apply, which use bulk_create
        # and would otherwise raise DataError on varchar(255).
        max_length = _logo_name_max_length()
        long_name = "z" * 600
        Logo.objects.bulk_create(
            [
                Logo(name=long_name, url="https://example.com/logo-bulk-1.png"),
                Logo(name="short", url="https://example.com/logo-bulk-2.png"),
            ],
            ignore_conflicts=True,
        )
        logo = Logo.objects.get(url="https://example.com/logo-bulk-1.png")
        self.assertEqual(len(logo.name), max_length)
        self.assertEqual(logo.name, long_name[:max_length])
        self.assertEqual(
            Logo.objects.get(url="https://example.com/logo-bulk-2.png").name,
            "short",
        )


class VODLogoNameTruncationModelTests(TestCase):
    def test_create_truncates_long_name(self):
        max_length = VODLogo._meta.get_field("name").max_length
        long_name = "Movie Title " + ("m" * 400)
        logo = VODLogo.objects.create(
            name=long_name,
            url="https://example.com/vod-create.png",
        )
        logo.refresh_from_db()
        self.assertEqual(logo.name, long_name[:max_length])

    def test_bulk_create_truncates_long_names(self):
        max_length = VODLogo._meta.get_field("name").max_length
        long_name = "Series " + ("s" * 400)
        VODLogo.objects.bulk_create(
            [VODLogo(name=long_name, url="https://example.com/vod-bulk.png")],
            ignore_conflicts=True,
        )
        logo = VODLogo.objects.get(url="https://example.com/vod-bulk.png")
        self.assertEqual(logo.name, long_name[:max_length])


class LogoSerializerNameTruncationTests(TestCase):
    def test_serializer_accepts_and_truncates_long_name(self):
        max_length = _logo_name_max_length()
        long_name = "n" * 400
        serializer = LogoSerializer(
            data={
                "name": long_name,
                "url": "https://example.com/logo-ser.png",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["name"],
            long_name[:max_length],
        )
        logo = serializer.save()
        self.assertEqual(logo.name, long_name[:max_length])


class VODLogoSerializerNameTruncationTests(TestCase):
    def test_serializer_accepts_and_truncates_long_name(self):
        max_length = VODLogo._meta.get_field("name").max_length
        long_name = "v" * 400
        serializer = VODLogoSerializer(
            data={
                "name": long_name,
                "url": "https://example.com/vod-ser.png",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(
            serializer.validated_data["name"],
            long_name[:max_length],
        )
        logo = serializer.save()
        self.assertEqual(logo.name, long_name[:max_length])


class ResolvePosterLogoNameLookupTests(TestCase):
    @patch("apps.channels.tasks.requests.get")
    def test_stage6_finds_logo_stored_with_truncated_name(self, mock_get):
        mock_get.return_value = MagicMock(ok=False)
        max_length = _logo_name_max_length()
        long_title = "Show " + ("t" * 400)
        logo = Logo.objects.create(
            name=long_title,
            url="https://example.com/poster-long-title.png",
        )
        self.assertEqual(len(logo.name), max_length)

        poster_logo_id, poster_url = _resolve_poster_for_program(
            "Some Channel",
            {"title": long_title},
        )
        self.assertEqual(poster_logo_id, logo.id)
        self.assertEqual(poster_url, logo.url)
