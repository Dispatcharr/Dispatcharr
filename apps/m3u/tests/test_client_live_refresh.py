from types import SimpleNamespace
from unittest.mock import ANY, patch

from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from apps.m3u.client_refresh import (
    handle_xc_live_catalog_request,
    wait_for_xc_live_refresh,
)
from apps.m3u.models import M3UAccount


def _user(*, enabled, interval_minutes=55):
    return SimpleNamespace(
        id=7,
        username="xc-user",
        custom_properties={
            "xc_live_refresh_on_request": enabled,
            "xc_live_refresh_request_interval_minutes": interval_minutes,
        },
    )


def _account(*, minutes_old=120, minimum_age_minutes=55):
    return SimpleNamespace(
        id=11,
        name="Provider One",
        status=M3UAccount.Status.SUCCESS,
        updated_at=timezone.now() - timezone.timedelta(minutes=minutes_old),
        xc_live_refresh_min_age_minutes=minimum_age_minutes,
    )


class ClientLiveRefreshTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get(
            "/player_api.php?action=get_live_streams",
            HTTP_USER_AGENT="XC Test Client",
            REMOTE_ADDR="192.0.2.10",
        )

    @patch("apps.m3u.client_refresh.log_system_event")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    def test_disabled_user_is_logged_but_does_not_query_accounts(
        self, cache_add, log_event
    ):
        with patch("apps.m3u.client_refresh._visible_live_accounts") as visible:
            result = handle_xc_live_catalog_request(
                self.request,
                _user(enabled=False),
            )

        visible.assert_not_called()
        self.assertEqual(result["queued"], [])
        self.assertEqual(result["skipped"], ["disabled for user"])
        log_event.assert_called_once()

    @patch("apps.m3u.client_refresh.log_system_event")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_stale_account_queues_live_only_refresh(
        self, apply_async, task_locked, cache_add, log_event
    ):
        account = _account(minutes_old=120)
        with patch(
            "apps.m3u.client_refresh._visible_live_accounts",
            return_value=[account],
        ):
            result = handle_xc_live_catalog_request(
                self.request,
                _user(enabled=True),
            )

        apply_async.assert_called_once_with(
            kwargs={
                "account_id": account.id,
                "include_vod": False,
                "minimum_age_seconds": 55 * 60,
                "skip_if_refreshed_after": ANY,
                "client_triggered": True,
            }
        )
        self.assertEqual(result["queued"], [account.name])
        log_event.assert_called_once()

    @patch("apps.m3u.client_refresh.log_system_event")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_recent_success_skips_refresh(self, apply_async, cache_add, log_event):
        account = _account(minutes_old=10)
        with patch(
            "apps.m3u.client_refresh._visible_live_accounts",
            return_value=[account],
        ):
            result = handle_xc_live_catalog_request(
                self.request,
                _user(enabled=True),
            )

        apply_async.assert_not_called()
        self.assertEqual(
            result["skipped"],
            [f"{account.name}: refreshed within 55m"],
        )

    @patch("apps.m3u.client_refresh.log_system_event")
    @patch("apps.m3u.client_refresh.cache.add", side_effect=[True, False, True])
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_provider_queue_key_coalesces_users(
        self, apply_async, task_locked, cache_add, log_event
    ):
        account = _account(minutes_old=120)
        with patch(
            "apps.m3u.client_refresh._visible_live_accounts",
            return_value=[account],
        ):
            result = handle_xc_live_catalog_request(
                self.request,
                _user(enabled=True),
            )

        apply_async.assert_not_called()
        self.assertEqual(result["skipped"], [f"{account.name}: already queued"])

    @patch("apps.m3u.client_refresh.log_system_event")
    @patch("apps.m3u.client_refresh.cache.add", side_effect=[False, True])
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    def test_user_request_interval_suppresses_repeated_requests(
        self, task_locked, cache_add, log_event
    ):
        account = _account(minutes_old=120)
        with patch(
            "apps.m3u.client_refresh._visible_live_accounts",
            return_value=[account],
        ):
            result = handle_xc_live_catalog_request(
                self.request,
                _user(enabled=True, interval_minutes=30),
            )

        self.assertEqual(result["queued"], [])
        self.assertEqual(
            result["skipped"],
            [f"{account.name}: user cooldown active (30m)"],
        )

    @patch("apps.m3u.client_refresh.log_system_event")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_zero_intervals_allow_every_request_to_queue(
        self, apply_async, task_locked, cache_add, log_event
    ):
        account = _account(minutes_old=0, minimum_age_minutes=0)
        with patch(
            "apps.m3u.client_refresh._visible_live_accounts",
            return_value=[account],
        ):
            result = handle_xc_live_catalog_request(
                self.request,
                _user(enabled=True, interval_minutes=0),
            )

        self.assertEqual(result["queued"], [account.name])
        apply_async.assert_called_once_with(
            kwargs={
                "account_id": account.id,
                "include_vod": False,
                "minimum_age_seconds": 0,
                "skip_if_refreshed_after": ANY,
                "client_triggered": True,
            }
        )
        self.assertNotIn(
            "xc_live_refresh_user_request:7:11",
            [call.args[0] for call in cache_add.call_args_list],
        )

    @patch("apps.m3u.client_refresh.cache.delete_many")
    @patch(
        "apps.m3u.client_refresh.cache.get_many",
        return_value={"xc_live_refresh_complete:test:11": "finished"},
    )
    def test_wait_returns_when_completion_marker_is_available(
        self,
        get_many,
        delete_many,
    ):
        result = wait_for_xc_live_refresh(
            ["xc_live_refresh_complete:test:11"],
            15,
        )

        self.assertEqual(result, {"completed": True, "pending": 0})
        delete_many.assert_called_once_with(
            {"xc_live_refresh_complete:test:11"}
        )

    @patch("apps.m3u.client_refresh.time.sleep")
    @patch(
        "apps.m3u.client_refresh.time.monotonic",
        side_effect=[100.0, 101.0],
    )
    @patch("apps.m3u.client_refresh.cache.get_many", return_value={})
    def test_wait_stops_at_timeout(self, get_many, monotonic, sleep):
        result = wait_for_xc_live_refresh(
            ["xc_live_refresh_complete:test:11"],
            1,
        )

        self.assertEqual(result, {"completed": False, "pending": 1})
        sleep.assert_not_called()
