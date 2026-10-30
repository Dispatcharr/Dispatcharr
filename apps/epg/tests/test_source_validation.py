"""XMLTV creation requires a usable source, including the upload path."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.epg.api_views import EPGSourceViewSet
from apps.epg.models import EPGSource
from apps.epg.serializers import EPGSourceSerializer


class EPGSourceValidationTests(TestCase):
    def test_empty_xmltv_source_is_rejected_before_creation_or_refresh(self):
        user_model = get_user_model()
        admin = user_model.objects.create_user(
            username='epg_validation_admin',
            password='test-only',
            user_level=user_model.UserLevel.ADMIN,
        )
        request = APIRequestFactory().post(
            '/api/epg/sources/',
            {'name': 'Empty guide', 'source_type': 'xmltv'},
            format='json',
        )
        force_authenticate(request, user=admin)
        with patch('apps.epg.signals.refresh_epg_data.delay') as refresh:
            response = EPGSourceViewSet.as_view({'post': 'create'})(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn('url', response.data)
        self.assertFalse(EPGSource.objects.exists())
        refresh.assert_not_called()

    def test_url_or_uploaded_file_is_accepted(self):
        for source in (
            {'url': 'https://example.invalid/guide.xml'},
            {'file_path': '/data/uploads/epgs/guide.xml'},
        ):
            with self.subTest(source=source):
                serializer = EPGSourceSerializer(data={
                    'name': 'Example guide', 'source_type': 'xmltv', **source,
                })
                self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_whitespace_is_not_a_source(self):
        serializer = EPGSourceSerializer(data={
            'name': 'Empty guide', 'source_type': 'xmltv',
            'url': ' ', 'file_path': ' ',
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn('url', serializer.errors)

    def test_existing_file_remains_valid_when_editing_without_a_url(self):
        source = EPGSource.objects.create(
            name='Uploaded guide', source_type='xmltv',
            file_path='/data/uploads/epgs/guide.xml', is_active=False,
        )
        serializer = EPGSourceSerializer(
            source, data={'url': ''}, partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_removing_the_last_source_is_rejected(self):
        source = EPGSource.objects.create(
            name='URL guide', source_type='xmltv',
            url='https://example.invalid/guide.xml', is_active=False,
        )
        serializer = EPGSourceSerializer(
            source, data={'url': ''}, partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn('url', serializer.errors)

    def test_legacy_empty_sources_can_still_be_disabled_or_renamed(self):
        source = EPGSource.objects.create(
            name='Legacy guide', source_type='xmltv', is_active=False,
        )
        serializer = EPGSourceSerializer(
            source, data={'name': 'Legacy renamed', 'is_active': False},
            partial=True,
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_other_source_types_do_not_require_xmltv_connection_fields(self):
        for source_type in ('dummy', 'schedules_direct'):
            with self.subTest(source_type=source_type):
                serializer = EPGSourceSerializer(data={
                    'name': 'Example guide', 'source_type': source_type,
                })
                self.assertTrue(serializer.is_valid(), serializer.errors)
