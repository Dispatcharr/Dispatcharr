from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.m3u.client_refresh import (
    _bounded_minutes,
    handle_xc_live_catalog_request,
    mark_client_refresh_complete,
    record_client_refresh_failure,
    record_client_refresh_outcome,
    wait_for_xc_live_refresh,
)
from apps.m3u.models import M3UAccount
from apps.m3u.tasks import refresh_single_m3u_account
from apps.output.views import _xc_stream_live_streams_with_refresh


class ClientLiveRefreshTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(
            id=7,
            custom_properties={
                "xc_live_refresh_on_request": True,
            },
        )
        self.account = SimpleNamespace(
            id=11,
            name="provider",
            xc_live_refresh_min_age_minutes=45,
            updated_at=timezone.now() - timedelta(hours=2),
            status=M3UAccount.Status.SUCCESS,
        )

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_opted_in_user_queues_live_only_refresh(
        self, visible_accounts, _lock, cache_add, apply_async
    ):
        visible_accounts.return_value = [self.account]

        handle_xc_live_catalog_request(self.user)

        self.assertEqual(cache_add.call_count, 1)
        self.assertEqual(cache_add.call_args.args[0], f"xc_live_refresh_request:{self.account.id}")
        kwargs = apply_async.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["account_id"], self.account.id)
        self.assertIs(kwargs["include_vod"], False)
        self.assertEqual(kwargs["minimum_age_seconds"], 45 * 60)
        self.assertTrue(kwargs["client_completion_key"].startswith("xc_live_refresh_complete:"))

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.cache.get", return_value=None)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_client_request_tracks_only_newly_queued_live_refreshes(
        self, visible_accounts, _lock, _cache_get, _cache_add, apply_async
    ):
        visible_accounts.return_value = [self.account]
        keys = handle_xc_live_catalog_request(self.user)
        kwargs = apply_async.call_args.kwargs["kwargs"]
        self.assertEqual(keys, [kwargs["client_completion_key"]])
        self.assertTrue(keys[0].startswith("xc_live_refresh_complete:"))
        self.assertIs(kwargs["include_vod"], False)
        self.assertEqual(kwargs["minimum_age_seconds"], 45 * 60)

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_client_request_respects_provider_cooldown(self, visible_accounts, apply_async):
        self.account.updated_at = timezone.now()
        visible_accounts.return_value = [self.account]
        self.assertEqual(
            handle_xc_live_catalog_request(self.user), []
        )
        apply_async.assert_not_called()

    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_disabled_user_does_not_query_providers(self, visible_accounts):
        self.user.custom_properties["xc_live_refresh_on_request"] = False
        self.assertEqual(handle_xc_live_catalog_request(self.user), [])
        visible_accounts.assert_not_called()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_recent_success_does_not_queue(self, visible_accounts, apply_async):
        self.account.updated_at = timezone.now() - timedelta(minutes=10)
        visible_accounts.return_value = [self.account]
        handle_xc_live_catalog_request(self.user)
        apply_async.assert_not_called()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.cache.get", return_value=None)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_default_cooldown_allows_refresh_at_thirty_minutes(
        self, visible_accounts, _lock, _cache_get, cache_add, apply_async
    ):
        now = timezone.now()
        self.account.xc_live_refresh_min_age_minutes = M3UAccount().xc_live_refresh_min_age_minutes
        visible_accounts.return_value = [self.account]
        for age, should_queue in ((29, False), (30, True)):
            with self.subTest(age=age), patch("apps.m3u.client_refresh.timezone.now", return_value=now):
                self.account.updated_at = now - timedelta(minutes=age)
                cache_add.reset_mock()
                apply_async.reset_mock()
                handle_xc_live_catalog_request(self.user)
                self.assertEqual(apply_async.called, should_queue)
                if should_queue:
                    self.assertEqual(
                        apply_async.call_args.kwargs["kwargs"]["minimum_age_seconds"], 30 * 60
                    )
                else:
                    cache_add.assert_not_called()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.delete")
    @patch("apps.m3u.client_refresh.cache.add", return_value=False)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_already_queued_provider_does_not_add_another_refresh(
        self, visible_accounts, _lock, cache_add, cache_delete, apply_async
    ):
        visible_accounts.return_value = [self.account]
        with patch("apps.m3u.client_refresh.cache.get", return_value=None):
            handle_xc_live_catalog_request(self.user)
        cache_add.assert_called_once()
        cache_delete.assert_not_called()
        apply_async.assert_not_called()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.cache.get", return_value=None)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_legacy_user_interval_does_not_limit_requests(
        self, visible_accounts, _lock, _cache_get, cache_add, apply_async
    ):
        self.user.custom_properties["xc_live_refresh_request_interval_minutes"] = 10080
        visible_accounts.return_value = [self.account]
        handle_xc_live_catalog_request(self.user)
        cache_add.assert_called_once()
        apply_async.assert_called_once()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.cache.get", return_value=None)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_retired_wait_settings_do_not_disable_completion_tracking(
        self, visible_accounts, _lock, _cache_get, _cache_add, apply_async
    ):
        self.user.custom_properties.update({
            "xc_live_refresh_wait_for_completion": False,
            "xc_live_refresh_wait_timeout_seconds": 60,
        })
        visible_accounts.return_value = [self.account]
        keys = handle_xc_live_catalog_request(self.user)
        self.assertEqual(keys, [apply_async.call_args.kwargs["kwargs"]["client_completion_key"]])

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add")
    @patch("apps.m3u.client_refresh.cache.get")
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_failure_backoff_is_shared_by_all_users(
        self, visible_accounts, _lock, cache_get, cache_add, apply_async
    ):
        visible_accounts.return_value = [self.account]
        cache_get.return_value = timezone.now().timestamp()
        for user_id in (7, 8):
            self.user.id = user_id
            handle_xc_live_catalog_request(self.user)
        cache_add.assert_not_called()
        apply_async.assert_not_called()
        self.assertEqual(cache_get.call_args.args[0], "xc_live_refresh_failure:11")

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.cache.get")
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_success_after_failure_overrides_old_backoff(
        self, visible_accounts, _lock, cache_get, _cache_add, apply_async
    ):
        self.account.xc_live_refresh_min_age_minutes = 0
        self.account.updated_at = timezone.now() - timedelta(seconds=5)
        cache_get.return_value = (timezone.now() - timedelta(seconds=30)).timestamp()
        visible_accounts.return_value = [self.account]
        handle_xc_live_catalog_request(self.user)
        apply_async.assert_called_once()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async", side_effect=RuntimeError("broker unavailable"))
    @patch("apps.m3u.client_refresh.record_client_refresh_failure")
    @patch("apps.m3u.client_refresh._release_reservation")
    @patch("apps.m3u.client_refresh.cache.add", return_value=True)
    @patch("apps.m3u.client_refresh.cache.get", return_value=None)
    @patch("apps.m3u.client_refresh.is_task_lock_held", return_value=False)
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_queue_failure_releases_reservation_and_backs_off(
        self, visible_accounts, _lock, _cache_get, _cache_add, release, failure, _queue
    ):
        visible_accounts.return_value = [self.account]
        handle_xc_live_catalog_request(self.user)
        self.assertEqual(release.call_args.args[0], "xc_live_refresh_request:11")
        failure.assert_called_once_with(11)


class ClientRefreshDefaultTests(SimpleTestCase):
    def test_new_accounts_default_to_thirty_minutes(self):
        self.assertEqual(M3UAccount().xc_live_refresh_min_age_minutes, 30)

    def test_invalid_values_fall_back_to_thirty_minutes(self):
        for value in (None, True, "invalid"):
            with self.subTest(value=value):
                self.assertEqual(_bounded_minutes(value), 30)

    def test_explicit_values_are_preserved(self):
        for value in (0, 45, 55):
            with self.subTest(value=value):
                self.assertEqual(_bounded_minutes(value), value)


class ClientRefreshOutcomeTests(SimpleTestCase):
    @patch("apps.m3u.client_refresh.mark_client_refresh_complete")
    @patch("apps.m3u.tasks._set_m3u_account_status")
    @patch("apps.m3u.tasks.M3UAccount.objects.filter")
    @patch("apps.m3u.tasks._ensure_m3u_refresh_terminal_status")
    @patch("apps.m3u.tasks._release_task_db_connection")
    @patch("apps.m3u.tasks.TaskLockRenewer")
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl")
    def test_worker_signals_completion_after_success_or_failure(
        self, impl, _acquire, _release, _renewer, _db,
        _ensure, _account, _status, mark,
    ):
        for error in (None, RuntimeError("provider unavailable")):
            with self.subTest(error=error):
                impl.side_effect = error
                mark.reset_mock()
                refresh_single_m3u_account(11, client_completion_key="job")
                mark.assert_called_once_with("job", "finished")

    @patch("apps.m3u.client_refresh.cache.set")
    def test_failure_has_a_short_provider_wide_expiration(self, cache_set):
        record_client_refresh_failure(11)
        self.assertEqual(cache_set.call_args.args[0], "xc_live_refresh_failure:11")
        self.assertEqual(cache_set.call_args.kwargs["timeout"], 60)

    @patch("apps.m3u.client_refresh.record_client_refresh_failure")
    @patch("apps.m3u.client_refresh.M3UAccount.objects.filter")
    def test_failed_refresh_records_backoff(self, account_filter, failure):
        account_filter.return_value.values_list.return_value.first.return_value = M3UAccount.Status.ERROR
        record_client_refresh_outcome(11)
        failure.assert_called_once_with(11)

    @patch("apps.m3u.client_refresh.cache.delete")
    @patch("apps.m3u.client_refresh.M3UAccount.objects.filter")
    def test_successful_refresh_clears_backoff(self, account_filter, cache_delete):
        account_filter.return_value.values_list.return_value.first.return_value = M3UAccount.Status.SUCCESS
        record_client_refresh_outcome(11)
        cache_delete.assert_called_once_with("xc_live_refresh_failure:11")

    @patch("apps.m3u.client_refresh.record_client_refresh_outcome")
    @patch("apps.m3u.client_refresh.release_client_refresh_reservation")
    @patch("apps.m3u.tasks._ensure_m3u_refresh_terminal_status")
    @patch("apps.m3u.tasks._release_task_db_connection")
    @patch("apps.m3u.tasks.TaskLockRenewer")
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl", return_value="done")
    def test_worker_records_outcome_after_terminal_status(
        self, _impl, _acquire, _release, _renewer, _db, ensure, _reservation, outcome
    ):
        self.assertEqual(refresh_single_m3u_account(11, client_request_token="queued"), "done")
        ensure.assert_called_once_with(11)
        outcome.assert_called_once_with(11)


class ConditionalTaskFreshnessTests(SimpleTestCase):
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl")
    @patch("apps.m3u.tasks.M3UAccount.objects.filter")
    def test_refresh_skips_recent_provider_update(
        self, account_filter, refresh_impl, _acquire, release
    ):
        account_filter.return_value.values_list.return_value.first.return_value = timezone.now()
        result = refresh_single_m3u_account(
            11,
            include_vod=False,
            minimum_age_seconds=3600,
        )
        self.assertIn("Skipped conditional", result)
        refresh_impl.assert_not_called()
        release.assert_called_once_with("refresh_single_m3u_account", 11)

    @patch("apps.m3u.client_refresh.mark_client_refresh_complete")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=False)
    def test_lock_race_completes_waiter_without_waiting_for_timeout(self, _acquire, mark):
        result = refresh_single_m3u_account(11, client_completion_key="job")
        self.assertIn("already running", result)
        mark.assert_called_once_with("job", "already_running")

    @patch("apps.m3u.client_refresh.mark_client_refresh_complete")
    @patch("apps.m3u.tasks.release_task_lock")
    @patch("apps.m3u.tasks.acquire_task_lock", return_value=True)
    @patch("apps.m3u.tasks._refresh_single_m3u_account_impl")
    @patch("apps.m3u.tasks.M3UAccount.objects.filter")
    def test_freshness_recheck_completes_waiter(
        self, account_filter, refresh_impl, _acquire, _release, mark
    ):
        account_filter.return_value.values_list.return_value.first.return_value = timezone.now()
        refresh_single_m3u_account(11, minimum_age_seconds=3600, client_completion_key="job")
        refresh_impl.assert_not_called()
        mark.assert_called_once_with("job", "skipped_fresh")


class ClientRefreshWaitTests(SimpleTestCase):
    @patch("apps.m3u.client_refresh.cache.get_many")
    def test_no_new_jobs_return_immediately(self, get_many):
        self.assertEqual(wait_for_xc_live_refresh([]), {"completed": True, "pending": 0})
        get_many.assert_not_called()

    @patch("apps.m3u.client_refresh.time.sleep")
    @patch("apps.m3u.client_refresh.cache.delete_many")
    @patch("apps.m3u.client_refresh.cache.get_many", return_value={"one": "finished", "two": "finished"})
    def test_all_finished_jobs_return_and_clear_markers(self, _get_many, delete_many, sleep):
        self.assertEqual(wait_for_xc_live_refresh(["one", "two"]), {"completed": True, "pending": 0})
        delete_many.assert_called_once_with({"one", "two"})
        sleep.assert_not_called()

    @patch("apps.m3u.client_refresh.time.sleep")
    @patch("apps.m3u.client_refresh.time.monotonic", side_effect=[0, 14.9, 15])
    @patch("apps.m3u.client_refresh.cache.delete_many")
    @patch("apps.m3u.client_refresh.cache.get_many", side_effect=[{"one": "finished"}, {}])
    def test_timeout_is_shared_across_all_providers(self, get_many, delete_many, _clock, sleep):
        self.assertEqual(wait_for_xc_live_refresh(["one", "two"]), {"completed": False, "pending": 1})
        self.assertEqual(get_many.call_count, 2)
        delete_many.assert_called_once_with({"one"})
        self.assertAlmostEqual(sleep.call_args.args[0], 0.1)
        sleep.assert_called_once()

    @patch("apps.m3u.client_refresh.cache.get_many", side_effect=RuntimeError("cache unavailable"))
    def test_cache_failure_does_not_break_the_client_response(self, _get_many):
        self.assertEqual(wait_for_xc_live_refresh(["job"]), {"completed": False, "pending": 1})

    @patch("apps.m3u.client_refresh.cache.set")
    def test_completion_marker_expires(self, cache_set):
        mark_client_refresh_complete("job", "finished")
        cache_set.assert_called_once_with("job", "finished", timeout=900)

    @patch("apps.m3u.client_refresh.cache.set")
    def test_background_refresh_needs_no_completion_marker(self, cache_set):
        mark_client_refresh_complete(None, "finished")
        cache_set.assert_not_called()


class ClientRefreshWaitResponseTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(custom_properties={
            "xc_live_refresh_on_request": True,
        })

    def test_client_refresh_waits_before_loading_the_catalog(self):
        events = []

        def queue(*_args, **_kwargs):
            events.append("queue")
            return ["job"]

        def wait_for_jobs(*_args):
            events.append("wait")

        def catalog(*_args):
            events.append("catalog")
            return iter(["[", "]"])

        with (
            patch(
                "apps.m3u.client_refresh.handle_xc_live_catalog_request",
                side_effect=queue,
            ) as handle,
            patch(
                "apps.m3u.client_refresh.wait_for_xc_live_refresh",
                side_effect=wait_for_jobs,
            ) as wait,
            patch("apps.output.views._xc_stream_live_streams", side_effect=catalog),
        ):
            self.assertEqual(list(_xc_stream_live_streams_with_refresh(None, self.user)), ["[", "]"])
            self.assertEqual(events, ["queue", "wait", "catalog"])
            handle.assert_called_once_with(self.user)
            wait.assert_called_once_with(["job"])

    @patch("apps.output.views._xc_stream_live_streams", return_value=iter(["[", "]"]))
    @patch("apps.m3u.client_refresh.time.sleep")
    @patch("apps.m3u.client_refresh._visible_live_accounts")
    def test_disabled_client_refresh_returns_catalog_without_waiting(self, visible, sleep, _stream):
        self.user.custom_properties["xc_live_refresh_on_request"] = False
        self.assertEqual(list(_xc_stream_live_streams_with_refresh(None, self.user)), ["[", "]"])
        visible.assert_not_called()
        sleep.assert_not_called()

    @patch("apps.output.views._xc_stream_live_streams", return_value=iter(["[", "]"]))
    @patch("apps.m3u.client_refresh.time.sleep")
    @patch("apps.m3u.client_refresh.cache.get_many")
    @patch("apps.m3u.client_refresh.handle_xc_live_catalog_request", return_value=[])
    def test_no_eligible_provider_returns_catalog_without_waiting(self, handle, get_many, sleep, _stream):
        self.assertEqual(list(_xc_stream_live_streams_with_refresh(None, self.user)), ["[", "]"])
        handle.assert_called_once_with(self.user)
        get_many.assert_not_called()
        sleep.assert_not_called()

    @patch("apps.output.views._xc_stream_live_streams", return_value=iter(["[", "]"]))
    @patch(
        "apps.m3u.client_refresh.wait_for_xc_live_refresh",
        return_value={"completed": False, "pending": 1},
    )
    @patch("apps.m3u.client_refresh.handle_xc_live_catalog_request", return_value=["job"])
    def test_timeout_still_returns_available_catalog(self, handle, wait, _stream):
        self.assertEqual(list(_xc_stream_live_streams_with_refresh(None, self.user)), ["[", "]"])
        handle.assert_called_once()
        wait.assert_called_once_with(["job"])

    @patch("apps.output.views._xc_stream_live_streams", return_value=iter(["[", "]"]))
    @patch(
        "apps.m3u.client_refresh.wait_for_xc_live_refresh",
        side_effect=RuntimeError("cache unavailable"),
    )
    @patch("apps.m3u.client_refresh.handle_xc_live_catalog_request", return_value=["job"])
    def test_coordinator_error_returns_catalog_without_queueing_twice(self, handle, _wait, _stream):
        self.assertEqual(list(_xc_stream_live_streams_with_refresh(None, self.user)), ["[", "]"])
        handle.assert_called_once()
