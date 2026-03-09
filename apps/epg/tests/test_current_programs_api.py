from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.epg.models import EPGSource, EPGData, ProgramData

User = get_user_model()

CURRENT_PROGRAMS_URL = "/api/epg/current-programs/"


class CurrentProgramsAPITests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass123"
        )
        self.user.user_level = 10
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        self.now = timezone.now()

        # Create an XMLTV source with programmes
        self.source = EPGSource.objects.create(
            name="Test XMLTV",
            source_type="xmltv",
            url="http://example.com/epg.xml",
        )
        self.epg_data = EPGData.objects.create(
            tvg_id="test.channel",
            name="Test Channel",
            epg_source=self.source,
        )
        self.program = ProgramData.objects.create(
            epg=self.epg_data,
            start_time=self.now - timezone.timedelta(hours=1),
            end_time=self.now + timezone.timedelta(hours=1),
            title="Current Show",
            description="A show currently airing",
            tvg_id="test.channel",
        )

        # Dummy EPG source
        self.dummy_source = EPGSource.objects.create(
            name="Dummy EPG",
            source_type="dummy",
        )
        self.dummy_epg = EPGData.objects.create(
            tvg_id="dummy.channel",
            name="Dummy Channel",
            epg_source=self.dummy_source,
        )

    def test_returns_program_for_current_time_window(self):
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": [self.epg_data.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["title"], "Current Show")
        self.assertEqual(response.data[0]["epg_data_id"], self.epg_data.id)

    def test_program_payload_has_expected_fields(self):
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": [self.epg_data.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

        payload = response.data[0]
        expected_keys = {
            "id",
            "start_time",
            "end_time",
            "title",
            "description",
            "sub_title",
            "tvg_id",
            "epg_data_id",
        }
        self.assertTrue(expected_keys.issubset(set(payload.keys())))
        self.assertEqual(payload["epg_data_id"], self.epg_data.id)

    @patch("apps.epg.api_views.find_current_program_for_tvg_id", return_value=None)
    def test_returns_empty_when_no_program_matches(self, mock_find):
        # Create EPG data with no DB programme and fallback returns None
        epg_no_prog = EPGData.objects.create(
            tvg_id="no.programme",
            name="No Programme Channel",
            epg_source=self.source,
        )
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": [epg_no_prog.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    @patch(
        "apps.epg.api_views.find_current_program_for_tvg_id",
        return_value="timeout",
    )
    def test_returns_parsing_sentinel_on_timeout(self, mock_find):
        epg_no_prog = EPGData.objects.create(
            tvg_id="timeout.channel",
            name="Timeout Channel",
            epg_source=self.source,
        )
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": [epg_no_prog.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertTrue(response.data[0]["parsing"])
        self.assertEqual(response.data[0]["epg_data_id"], epg_no_prog.id)

    def test_400_when_both_channel_uuids_and_epg_data_ids(self):
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"channel_uuids": ["abc"], "epg_data_ids": [1]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not both", response.data["error"])

    def test_skips_dummy_epg_sources(self):
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": [self.dummy_epg.id]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

    def test_enforces_50_id_limit(self):
        # Create 55 EPG entries, each with a current programme so DB lookup
        # handles them all (no fallback to find_current_program_for_tvg_id).
        ids = []
        for i in range(55):
            epg = EPGData.objects.create(
                tvg_id=f"limit.{i}",
                name=f"Limit Channel {i}",
                epg_source=self.source,
            )
            ProgramData.objects.create(
                epg=epg,
                start_time=self.now - timezone.timedelta(hours=1),
                end_time=self.now + timezone.timedelta(hours=1),
                title=f"Show {i}",
                tvg_id=f"limit.{i}",
            )
            ids.append(epg.id)

        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": ids},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # The view truncates to 50 IDs, so at most 50 results
        self.assertLessEqual(len(response.data), 50)

    def test_400_for_non_integer_epg_data_ids(self):
        response = self.client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": ["abc", "def"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("valid integers", response.data["error"])

    def test_auth_required(self):
        anon_client = APIClient()
        response = anon_client.post(
            CURRENT_PROGRAMS_URL,
            {"epg_data_ids": [self.epg_data.id]},
            format="json",
        )
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
