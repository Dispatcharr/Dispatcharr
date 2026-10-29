from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.plugins.manifest_messages import official_messages_for_user, reconcile_official_messages
from apps.plugins.models import PluginManifestMessageDismissal, PluginRepo
from core.models import SystemNotification


MESSAGE_ID = "5fba1255-b2d7-4d7a-bf4c-1338dfd8c94e"


def message(**overrides):
    result = {"id": MESSAGE_ID, "severity": "info", "body": "Notice"}
    result.update(overrides)
    return result


class ManifestMessageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="messages", password="x")

    def make_repo(self, **overrides):
        defaults = {
            "name": "Official", "url": "https://example.test/manifest.json", "is_official": True,
            "signature_verified": True, "cached_manifest": {"manifest": {"messages": [message()]}},
        }
        defaults.update(overrides)
        return PluginRepo.objects.create(**defaults)

    def test_only_verified_official_messages_are_returned(self):
        self.make_repo()
        self.assertEqual([entry["id"] for entry in official_messages_for_user(self.user)], [MESSAGE_ID])

        PluginRepo.objects.update(is_official=False)
        self.assertEqual(official_messages_for_user(self.user), [])

    def test_invalid_entries_are_skipped_without_hiding_valid_entries(self):
        self.make_repo(cached_manifest={"manifest": {"messages": [
            {"id": "not-a-uuid", "severity": "warning", "body": "bad"}, message(title="Good"),
        ]}})
        self.assertEqual(official_messages_for_user(self.user)[0]["title"], "Good")

    def test_schedule_target_and_dismissal_filter_messages(self):
        self.make_repo(cached_manifest={"manifest": {"messages": [
            message(starts_at="2020-01-01T00:00:00Z", expires_at="2030-01-01T00:00:00Z", target=">=0.0.0"),
        ]}})
        self.assertEqual(len(official_messages_for_user(self.user)), 1)
        PluginManifestMessageDismissal.objects.create(user=self.user, message_id=MESSAGE_ID)
        self.assertEqual(official_messages_for_user(self.user), [])

    @patch("core.utils.send_websocket_notification")
    def test_warning_creates_notification_once_and_deactivates_when_expired(self, websocket):
        repo = self.make_repo(cached_manifest={"manifest": {"messages": [message(severity="warning")]}})
        reconcile_official_messages(repo)
        notification = SystemNotification.objects.get(notification_key=f"plugin-manifest-message-{MESSAGE_ID}")
        self.assertEqual(notification.priority, SystemNotification.Priority.HIGH)
        websocket.assert_called_once()

        reconcile_official_messages(repo)
        websocket.assert_called_once()
        repo.cached_manifest = {"manifest": {"messages": [message(
            severity="warning", starts_at="2020-01-01T00:00:00Z", expires_at="2021-01-01T00:00:00Z"
        )]}}
        repo.save()
        reconcile_official_messages(repo)
        notification.refresh_from_db()
        self.assertFalse(notification.is_active)
