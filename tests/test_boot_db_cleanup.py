"""AppConfig boot ORM must return geventpool checkouts."""

from unittest.mock import MagicMock, patch

from django.apps import apps
from django.test import SimpleTestCase

from core.models import CoreSettings


class BootDbCleanupTests(SimpleTestCase):
    @patch("django.db.close_old_connections")
    @patch("core.developer_notifications.sync_developer_notifications")
    def test_developer_notifications_sync_closes_connections(
        self, _mock_sync, mock_close
    ):
        apps.get_app_config("core")._sync_developer_notifications()
        mock_close.assert_called_once()

    @patch("django.db.close_old_connections")
    @patch(
        "core.developer_notifications.sync_developer_notifications",
        side_effect=RuntimeError("sync failed"),
    )
    def test_developer_notifications_sync_closes_on_error(
        self, _mock_sync, mock_close
    ):
        apps.get_app_config("core")._sync_developer_notifications()
        mock_close.assert_called_once()

    @patch("django.db.close_old_connections")
    @patch("apps.backups.scheduler._sync_periodic_task")
    @patch("core.models.CoreSettings.objects.get_or_create")
    def test_backup_scheduler_sync_closes_connections(
        self, _mock_get_or_create, _mock_sync, mock_close
    ):
        apps.get_app_config("backups")._sync_backup_scheduler()
        mock_close.assert_called_once()

    @patch("django.db.close_old_connections")
    @patch(
        "apps.backups.scheduler._sync_periodic_task",
        side_effect=RuntimeError("sync failed"),
    )
    @patch("core.models.CoreSettings.objects.get_or_create")
    def test_backup_scheduler_sync_closes_on_error(
        self, _mock_get_or_create, _mock_sync, mock_close
    ):
        apps.get_app_config("backups")._sync_backup_scheduler()
        mock_close.assert_called_once()

    @patch("django.db.close_old_connections")
    @patch(
        "dispatcharr.app_initialization.should_skip_initialization",
        return_value=False,
    )
    @patch("core.scheduling.create_or_update_periodic_task")
    @patch(
        "core.models.CoreSettings.objects.get",
        side_effect=CoreSettings.DoesNotExist,
    )
    def test_plugin_repo_schedule_closes_connections(
        self, _mock_get, mock_create, _mock_skip, mock_close
    ):
        apps.get_app_config("plugins")._setup_repo_refresh_schedule()
        mock_create.assert_called_once()
        mock_close.assert_called_once()

    @patch("django.db.close_old_connections")
    @patch(
        "dispatcharr.app_initialization.should_skip_initialization",
        return_value=False,
    )
    @patch(
        "core.scheduling.create_or_update_periodic_task",
        side_effect=RuntimeError("schedule failed"),
    )
    @patch("core.models.CoreSettings.objects.get")
    def test_plugin_repo_schedule_closes_on_error(
        self, mock_get, _mock_create, _mock_skip, mock_close
    ):
        mock_get.return_value = MagicMock(value={"refresh_interval_hours": 6})
        apps.get_app_config("plugins")._setup_repo_refresh_schedule()
        mock_close.assert_called_once()
