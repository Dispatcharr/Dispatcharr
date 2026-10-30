"""System-event history is diagnostic output, independent of UI masking."""

from copy import deepcopy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from core.api_views import get_system_events
from core.models import SystemEvent
from core.utils import log_system_event
from dispatcharr.log_redaction import REDACTED, redact_log_data


class SystemEventRedactionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="event_privacy_admin",
            password="test-password",
            user_level=user_model.UserLevel.ADMIN,
        )
        self.factory = APIRequestFactory()
        self.details = {
            "message": (
                "Failed to authenticate: 403 Forbidden for url: "
                "https://provider.invalid/player_api.php"
                "?username=provider-user&password=provider-password"
                "&action=get_live_streams"
            ),
            "url": (
                "https://provider.invalid/live/provider-user/provider-password/123.ts"
            ),
            "credentials": [
                {"username": "provider-user", "password": "provider-password"}
            ],
            "account_name": "Example provider",
            "status": 403,
            "attempts": 3,
        }

    def get_events(self):
        request = self.factory.get("/api/core/system-events/")
        force_authenticate(request, user=self.admin)
        response = get_system_events(request)
        self.assertEqual(response.status_code, 200)
        return response.data["events"]

    def test_existing_history_is_redacted_on_read_without_rewriting_database(self):
        event = SystemEvent.objects.create(
            event_type="m3u_error",
            channel_name="Example channel",
            details=self.details,
        )
        result = next(row for row in self.get_events() if row["id"] == event.pk)
        self.assertEqual(result["details"], redact_log_data(self.details))
        self.assertEqual(result["details"]["status"], 403)
        self.assertEqual(result["details"]["attempts"], 3)
        self.assertEqual(result["channel_name"], "Example channel")
        self.assertIn("action=get_live_streams", result["details"]["message"])
        for value in ("provider.invalid", "provider-user", "provider-password"):
            self.assertNotIn(value, str(result))
        event.refresh_from_db()
        self.assertEqual(event.details, self.details)

    def test_new_events_store_redacted_details_but_preserve_integration_payload(self):
        original = deepcopy(self.details)
        with (
            patch("core.utils._dispatch_system_event_integrations") as dispatch,
            patch("core.utils._is_gevent_monkey_patched", return_value=False),
            patch("core.models.CoreSettings.get_system_settings", return_value={}),
        ):
            log_system_event(
                "m3u_error", channel_name="Example channel", **self.details,
            )
        event = SystemEvent.objects.get(event_type="m3u_error")
        self.assertEqual(event.details, redact_log_data(original))
        self.assertEqual(event.details["credentials"][0]["password"], REDACTED)
        self.assertEqual(self.details, original)
        dispatch.assert_called_once_with(
            "m3u_error", channel_id=None, channel_name="Example channel", **original,
        )
        result = next(row for row in self.get_events() if row["id"] == event.pk)
        self.assertEqual(result["details"], event.details)

    def test_credential_urls_in_channel_names_are_redacted(self):
        name = "https://provider.invalid/live/provider-user/provider-password/123.ts"
        event = SystemEvent.objects.create(
            event_type="channel_error", channel_name=name,
        )
        result = next(row for row in self.get_events() if row["id"] == event.pk)
        self.assertEqual(result["channel_name"], redact_log_data(name))
        with (
            patch("core.utils._dispatch_system_event_integrations"),
            patch("core.utils._is_gevent_monkey_patched", return_value=False),
            patch("core.models.CoreSettings.get_system_settings", return_value={}),
        ):
            log_system_event("channel_start", channel_name=name)
        stored = SystemEvent.objects.get(event_type="channel_start")
        self.assertEqual(stored.channel_name, redact_log_data(name))

    def test_redaction_expansion_cannot_exceed_channel_name_storage_limit(self):
        name = ("password=x " * 20).strip()
        max_length = SystemEvent._meta.get_field("channel_name").max_length
        self.assertLessEqual(len(name), max_length)
        self.assertGreater(len(redact_log_data(name)), max_length)
        with (
            patch("core.utils._dispatch_system_event_integrations"),
            patch("core.utils._is_gevent_monkey_patched", return_value=False),
            patch("core.models.CoreSettings.get_system_settings", return_value={}),
        ):
            log_system_event("channel_start", channel_name=name)
        stored = SystemEvent.objects.get(event_type="channel_start")
        self.assertEqual(stored.channel_name, redact_log_data(name)[:max_length])
