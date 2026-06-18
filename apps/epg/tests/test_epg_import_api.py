from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.epg.models import EPGSource

User = get_user_model()

IMPORT_URL = "/api/epg/import/"


class EPGImportAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="epg_import_admin", password="testpass123"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("apps.epg.api_views.refresh_epg_data.delay")
    def test_import_dummy_source_rejected_without_dispatch(self, mock_delay):
        source = EPGSource.objects.create(
            name="Dummy EPG",
            source_type="dummy",
        )

        response = self.client.post(
            IMPORT_URL, {"id": source.id}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        mock_delay.assert_not_called()

    @patch("apps.epg.api_views.refresh_epg_data.delay")
    def test_import_xmltv_dispatches_without_loading_programme_index(
        self, mock_delay
    ):
        source = EPGSource.objects.create(
            name="Large Index XMLTV",
            source_type="xmltv",
            url="http://example.com/epg.xml",
            programme_index={
                "channels": {f"ch.{i}": {"offsets": [0, 100]} for i in range(200)},
                "interleaved_channels": [],
            },
        )
        mock_delay.reset_mock()

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.post(
                IMPORT_URL, {"id": source.id}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(response.data["success"])
        mock_delay.assert_called_once_with(source.id, force=False)
        for query in ctx.captured_queries:
            self.assertNotIn(
                "programme_index",
                query["sql"].lower(),
                "import trigger should not read programme_index",
            )

    @patch("apps.epg.api_views.refresh_epg_data.delay")
    def test_import_missing_source_still_dispatches(self, mock_delay):
        response = self.client.post(IMPORT_URL, {"id": 99999}, format="json")

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once_with(99999, force=False)

    @patch("apps.epg.api_views.refresh_epg_data.delay")
    def test_import_honours_force_flag(self, mock_delay):
        source = EPGSource.objects.create(
            name="Force XMLTV",
            source_type="xmltv",
            url="http://example.com/epg.xml",
        )
        mock_delay.reset_mock()

        response = self.client.post(
            IMPORT_URL,
            {"id": source.id, "force": True},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once_with(source.id, force=True)
