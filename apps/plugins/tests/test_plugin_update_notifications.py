"""Plugin update notifications must track install_status, not accumulate.

evaluate_plugin_update_notification() is the single place that turns a
computed install_status into a SystemNotification; if it stops deleting
stale notifications (or stops broadcasting the dismissal) users end up with
permanent "update available" banners for plugins that are no longer
out of date, unmanaged, or removed.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.plugins.models import PluginConfig, PluginRepo
from apps.plugins.tasks import evaluate_plugin_update_notification, refresh_plugin_repos
from core.models import SystemNotification


class EvaluatePluginUpdateNotificationTests(TestCase):
    def test_update_available_creates_notification(self):
        with patch("core.utils.send_websocket_notification") as mock_send:
            key = evaluate_plugin_update_notification(
                "my-plugin", "My Plugin", "1.0.0", "2.0.0", "update_available"
            )

        self.assertEqual(key, "plugin-update-my-plugin")
        notification = SystemNotification.objects.get(notification_key=key)
        self.assertEqual(
            notification.notification_type, SystemNotification.NotificationType.PLUGIN_UPDATE
        )
        self.assertEqual(notification.priority, SystemNotification.Priority.NORMAL)
        self.assertTrue(notification.admin_only)
        self.assertTrue(notification.is_active)
        self.assertIn("My Plugin", notification.title)
        self.assertIn("1.0.0", notification.message)
        self.assertIn("2.0.0", notification.message)
        self.assertEqual(
            notification.action_data,
            {
                "plugin_key": "my-plugin",
                "installed_version": "1.0.0",
                "latest_version": "2.0.0",
                "action_url": "/plugins/my-plugin",
                "action_text": "View Plugin",
            },
        )
        mock_send.assert_called_once_with(notification)

    def test_update_available_is_idempotent(self):
        with patch("core.utils.send_websocket_notification"):
            evaluate_plugin_update_notification(
                "my-plugin", "My Plugin", "1.0.0", "2.0.0", "update_available"
            )
            evaluate_plugin_update_notification(
                "my-plugin", "My Plugin", "1.0.0", "3.0.0", "update_available"
            )

        self.assertEqual(
            SystemNotification.objects.filter(notification_key="plugin-update-my-plugin").count(),
            1,
        )
        notification = SystemNotification.objects.get(notification_key="plugin-update-my-plugin")
        self.assertIn("3.0.0", notification.message)

    def test_non_update_status_deletes_existing_notification(self):
        with patch("core.utils.send_websocket_notification"):
            evaluate_plugin_update_notification(
                "my-plugin", "My Plugin", "1.0.0", "2.0.0", "update_available"
            )

        with patch("core.utils.send_notification_dismissed") as mock_dismissed:
            result = evaluate_plugin_update_notification(
                "my-plugin", "My Plugin", "2.0.0", "2.0.0", "up_to_date"
            )

        self.assertIsNone(result)
        self.assertFalse(
            SystemNotification.objects.filter(notification_key="plugin-update-my-plugin").exists()
        )
        mock_dismissed.assert_called_once_with("plugin-update-my-plugin")

    def test_non_update_status_is_a_noop_when_nothing_exists(self):
        with patch("core.utils.send_notification_dismissed") as mock_dismissed:
            result = evaluate_plugin_update_notification(
                "my-plugin", "My Plugin", "2.0.0", "2.0.0", "up_to_date"
            )

        self.assertIsNone(result)
        mock_dismissed.assert_not_called()


class RefreshPluginReposNotificationSweepTests(TestCase):
    def _make_repo(self, **overrides):
        defaults = {
            "name": "Test Repo",
            "url": "https://example.com/manifest.json",
            "enabled": True,
            "cached_manifest": {"manifest": {"plugins": []}},
        }
        defaults.update(overrides)
        return PluginRepo.objects.create(**defaults)

    def _make_config(self, repo, **overrides):
        defaults = {
            "key": "my-plugin",
            "name": "My Plugin",
            "version": "1.0.0",
            "slug": "my-plugin",
            "source_repo": repo,
        }
        defaults.update(overrides)
        return PluginConfig.objects.create(**defaults)

    @patch("apps.plugins.api_views._unmanage_dropped_slugs", return_value=None)
    @patch("apps.plugins.api_views._save_fetched_manifest_to_repo", return_value=None)
    @patch("apps.plugins.api_views._fetch_manifest")
    def test_sweep_clears_notification_for_plugin_no_longer_out_of_date(
        self, mock_fetch, mock_save, mock_unmanage
    ):
        repo = self._make_repo(
            cached_manifest={
                "manifest": {"plugins": [{"slug": "my-plugin", "latest_version": "1.0.0"}]}
            }
        )
        self._make_config(repo, version="1.0.0")

        # Simulate a leftover notification from a previous refresh, before the
        # plugin was updated to the latest version.
        SystemNotification.objects.create(
            notification_key="plugin-update-my-plugin",
            notification_type=SystemNotification.NotificationType.PLUGIN_UPDATE,
            title="Plugin Update Available: My Plugin",
            message="stale",
            is_active=True,
            admin_only=True,
        )
        mock_fetch.return_value = ({}, True)

        with patch("core.utils.send_websocket_notification"), patch(
            "core.utils.send_notification_dismissed"
        ) as mock_dismissed:
            refresh_plugin_repos()

        self.assertFalse(
            SystemNotification.objects.filter(notification_key="plugin-update-my-plugin").exists()
        )
        mock_dismissed.assert_any_call("plugin-update-my-plugin")

    @patch("apps.plugins.api_views._unmanage_dropped_slugs", return_value=None)
    @patch("apps.plugins.api_views._save_fetched_manifest_to_repo", return_value=None)
    @patch("apps.plugins.api_views._fetch_manifest")
    def test_sweep_removes_stale_notification_for_removed_plugin(
        self, mock_fetch, mock_save, mock_unmanage
    ):
        repo = self._make_repo(cached_manifest={"manifest": {"plugins": []}})
        mock_fetch.return_value = ({}, True)

        # No PluginConfig exists for this key anymore (e.g. uninstalled), but
        # a stale "update available" notification is still active.
        SystemNotification.objects.create(
            notification_key="plugin-update-removed-plugin",
            notification_type=SystemNotification.NotificationType.PLUGIN_UPDATE,
            title="Plugin Update Available: Removed Plugin",
            message="stale",
            is_active=True,
            admin_only=True,
        )

        with patch("core.utils.send_websocket_notification"), patch(
            "core.utils.send_notification_dismissed"
        ) as mock_dismissed:
            refresh_plugin_repos()

        self.assertFalse(
            SystemNotification.objects.filter(
                notification_key="plugin-update-removed-plugin"
            ).exists()
        )
        mock_dismissed.assert_any_call("plugin-update-removed-plugin")
