"""Guided setup persists progress and never recreates an account or EPG on retry."""

from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.exceptions import APIException
from rest_framework.test import APIClient

from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.epg.models import EPGData, EPGSource
from apps.m3u.account_setup import (
    advance_account_setup,
    discover_setup_categories,
)
from apps.m3u.models import M3UAccount
from apps.m3u.serializers import M3UAccountSerializer


class AccountSetupTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_user(
            username="setup-admin", user_level=10
        )
        self.client.force_authenticate(self.admin)
        for target in (
            "apps.m3u.api_views.refresh_m3u_groups",
            "apps.m3u.signals.refresh_m3u_groups.delay",
            "apps.m3u.tasks.prepare_account_setup.delay",
            "apps.epg.signals.refresh_epg_data.delay",
        ):
            patcher = patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)

    def account(self, **values):
        return M3UAccount.objects.create(
            **{
                "name": "Example setup",
                "account_type": "XC",
                "server_url": "https://provider.example.invalid/base/player_api.php",
                "username": "example&user",
                "password": "example?password&=",
                "setup_step": "epg",
                **values,
            }
        )

    def action(self, account, action):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                f"/api/m3u/accounts/{account.id}/setup/",
                {"action": action},
                format="json",
            )

    def group(self, account):
        return ChannelGroupM3UAccount.objects.create(
            m3u_account=account,
            channel_group=ChannelGroup.objects.create(name="Example category"),
            enabled=True,
        )

    def test_new_xc_and_standard_accounts_start_at_their_next_setup_step(self):
        for kind, step in (("XC", "epg"), ("STD", "categories")):
            with self.subTest(kind=kind):
                response = self.client.post(
                    "/api/m3u/accounts/",
                    {
                        "name": f"New {kind}",
                        "account_type": kind,
                        "server_url": "https://provider.example.invalid",
                        "username": "example",
                        "password": "example",
                        "start_setup": True,
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 201, response.data)
                self.assertEqual(response.data["setup_step"], step)
                self.assertNotIn("start_setup", response.data)

    def test_api_clients_without_guided_setup_keep_existing_behavior(self):
        serializer = M3UAccountSerializer(
            data={"name": "Existing API workflow", "account_type": "XC"}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.save().setup_step, "")

    def test_new_guided_accounts_require_connection_details(self):
        for kind, fields in (
            ("XC", {"server_url", "username", "password"}),
            ("STD", {"server_url"}),
        ):
            serializer = M3UAccountSerializer(
                data={
                    "name": "Missing details",
                    "account_type": kind,
                    "start_setup": True,
                }
            )
            self.assertFalse(serializer.is_valid())
            self.assertEqual(set(serializer.errors), fields)

    def test_file_source_is_valid_for_standard_guided_setup(self):
        serializer = M3UAccountSerializer(
            data={
                "name": "File setup",
                "account_type": "STD",
                "start_setup": True,
                "file_path": "/data/example.m3u",
            }
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)

    @patch("apps.m3u.api_views.os.remove")
    @patch("apps.m3u.api_views.os.path.exists", return_value=True)
    @patch("apps.m3u.api_views.os.makedirs")
    @patch("builtins.open")
    def test_switch_to_uploaded_file_clears_old_url(
        self, open_file, makedirs, exists, remove
    ):
        account = self.account(account_type="STD", setup_step="categories")
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {
                "account_type": "STD",
                "server_url": "",
                "file": SimpleUploadedFile("example.m3u", b"#EXTM3U\n"),
            },
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.data)
        account.refresh_from_db()
        self.assertFalse(account.server_url)
        self.assertEqual(account.file_path, "/data/uploads/m3us/example.m3u")
        remove.assert_not_called()

    @patch("apps.m3u.api_views.os.remove")
    @patch("apps.m3u.api_views.os.path.exists", return_value=True)
    @patch("apps.m3u.api_views.os.makedirs")
    @patch("builtins.open")
    def test_replacing_same_filename_does_not_delete_the_new_upload(
        self, open_file, makedirs, exists, remove
    ):
        account = self.account(
            account_type="STD", server_url="",
            file_path="/data/uploads/m3us/example.m3u",
        )
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {"file": SimpleUploadedFile("example.m3u", b"#EXTM3U\n")},
            format="multipart",
        )
        self.assertEqual(response.status_code, 200, response.data)
        remove.assert_not_called()

    def test_switch_to_url_clears_file_and_file_edits_keep_saved_source(self):
        account = self.account(
            account_type="STD", server_url="",
            file_path="/data/uploads/m3us/example.m3u",
        )
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {"name": "Renamed file", "server_url": ""}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        account.refresh_from_db()
        self.assertEqual(account.file_path, "/data/uploads/m3us/example.m3u")
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {"server_url": "https://provider.example.invalid/playlist.m3u", "file_path": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        account.refresh_from_db()
        self.assertEqual(account.server_url, "https://provider.example.invalid/playlist.m3u")
        self.assertFalse(account.file_path)

    def test_refresh_error_and_normal_edits_preserve_the_setup_step(self):
        account = self.account(status="error", last_message="Provider denied access")
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {"name": "Edited setup", "setup_step": "", "start_setup": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "epg")
        response = self.client.get(f"/api/m3u/accounts/{account.id}/")
        self.assertEqual(response.data["setup_step"], "epg")
        self.assertEqual(response.data["status"], "error")

    @patch("apps.epg.signals.refresh_epg_data.delay")
    def test_epg_retry_preserves_base_path_and_credentials(self, refresh):
        account = self.account()
        for _ in range(2):
            response = self.action(account, "create_epg")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["setup_step"], "categories")
        self.assertEqual(EPGSource.objects.count(), 1)
        self.assertEqual(M3UAccount.objects.filter(name=account.name).count(), 1)
        url = urlsplit(EPGSource.objects.get().url)
        self.assertEqual(url.path, "/base/xmltv.php")
        self.assertEqual(
            parse_qs(url.query),
            {"username": [account.username], "password": [account.password]},
        )
        refresh.assert_called_once()

    def test_account_type_edits_align_unfinished_setup(self):
        for previous_type, step, new_type, expected_step in (
            ("XC", "epg", "STD", "categories"),
            ("XC", "categories", "STD", "categories"),
            ("STD", "categories", "XC", "epg"),
            ("XC", "categories", "XC", "categories"),
            ("STD", "epg", "STD", "categories"),
            ("XC", "account", "STD", "account"),
            ("STD", "content", "XC", "content"),
        ):
            with self.subTest(previous_type=previous_type, step=step):
                account = self.account(
                    name=f"Type change {previous_type} {step} {new_type}",
                    account_type=previous_type,
                    setup_step=step,
                    refresh_interval=24,
                )
                response = self.client.patch(
                    f"/api/m3u/accounts/{account.id}/",
                    {"account_type": new_type},
                    format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data["setup_step"], expected_step)
                account.refresh_from_db()
                self.assertEqual(account.setup_step, expected_step)
                self.assertFalse(account.refresh_task.enabled)
        self.assertFalse(EPGSource.objects.exists())

    @patch("apps.m3u.tasks.refresh_single_m3u_account.delay")
    @patch("apps.m3u.tasks.prepare_account_setup.delay")
    def test_navigation_is_sequential_persisted_and_retry_safe(self, discover, refresh):
        account_count = M3UAccount.objects.count()
        for kind, route in (
            ("XC", [
                ("back_to_epg", "epg"),
                ("back_to_content", "content"),
                ("back_to_account", "account"),
                ("continue_content", "content"),
                ("continue_epg", "epg"),
                ("skip_epg", "categories"),
            ]),
            ("STD", [
                ("back_to_content", "content"),
                ("back_to_account", "account"),
                ("continue_content", "content"),
                ("continue_categories", "categories"),
            ]),
        ):
            account = self.account(
                name=f"Navigate {kind}", account_type=kind,
                setup_step="categories", refresh_interval=24,
            )
            for action, target in route:
                for _ in range(2):
                    response = self.action(account, action)
                    self.assertEqual(response.status_code, 200, response.data)
                    self.assertEqual(response.data["setup_step"], target)
                response = self.client.get(f"/api/m3u/accounts/{account.id}/")
                self.assertEqual(response.data["setup_step"], target)
                account.refresh_from_db()
                self.assertFalse(account.refresh_task.enabled)
        self.assertEqual(M3UAccount.objects.count(), account_count + 2)
        self.assertFalse(EPGSource.objects.exists())
        discover.assert_not_called()
        refresh.assert_not_called()

    def test_navigation_cannot_skip_steps_or_restart_completed_setup(self):
        for kind, stage, action in (
            ("XC", "categories", "back_to_content"),
            ("XC", "account", "continue_epg"),
            ("STD", "categories", "back_to_epg"),
            ("STD", "content", "continue_epg"),
            ("XC", "", "back_to_epg"),
            ("STD", "", "continue_categories"),
        ):
            account = self.account(
                name=f"Invalid {kind} {stage} {action}",
                account_type=kind, setup_step=stage,
            )
            response = self.action(account, action)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["setup_step"], stage)

    @patch("apps.epg.signals.refresh_epg_data.delay")
    def test_back_to_epg_reuses_existing_source(self, refresh):
        account = self.account()
        self.action(account, "create_epg")
        self.action(account, "back_to_epg")
        self.action(account, "create_epg")
        self.assertEqual(EPGSource.objects.count(), 1)
        refresh.assert_called_once()

    @patch("apps.vod.tasks.refresh_vod_content.delay")
    def test_content_corrections_do_not_import_vod_before_finish(self, refresh):
        account = self.account(setup_step="content")
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {"enable_vod": True}, format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["setup_step"], "content")
        refresh.assert_not_called()

    def test_account_type_edits_do_not_restart_completed_setup(self):
        for previous_type, new_type in (("XC", "STD"), ("STD", "XC")):
            with self.subTest(previous_type=previous_type):
                account = self.account(
                    name=f"Completed {previous_type}",
                    account_type=previous_type,
                    setup_step="",
                )
                response = self.client.patch(
                    f"/api/m3u/accounts/{account.id}/",
                    {"account_type": new_type},
                    format="json",
                )
                self.assertEqual(response.status_code, 200, response.data)
                account.refresh_from_db()
                self.assertEqual(account.setup_step, "")

    def test_skipping_epg_is_persisted_without_creating_a_source(self):
        account = self.account()
        response = self.action(account, "skip_epg")
        self.assertEqual(response.status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "categories")
        self.assertFalse(EPGSource.objects.exists())

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_automatic_refreshes_wait_until_setup_is_complete(self, refresh):
        account = self.account(
            custom_properties={"enable_vod": True},
            refresh_interval=24,
            vod_refresh_after_live=False,
            vod_refresh_interval=6,
        )
        self.assertFalse(account.refresh_task.enabled)
        self.assertFalse(account.vod_refresh_task.enabled)
        self.action(account, "skip_epg")
        account.refresh_from_db()
        self.assertFalse(account.refresh_task.enabled)
        self.group(account)
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        self.assertEqual(self.action(account, "complete").status_code, 200)
        account.refresh_from_db()
        self.assertTrue(account.refresh_task.enabled)
        self.assertTrue(account.vod_refresh_task.enabled)
        self.assertFalse(EPGSource.objects.exists())

    def test_epg_validation_failure_leaves_step_resumable(self):
        account = self.account()
        EPGSource.objects.create(name=account.name, source_type="dummy")
        response = self.action(account, "create_epg")
        self.assertEqual(response.status_code, 400)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "epg")
        self.assertEqual(EPGSource.objects.count(), 1)

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_completion_queues_initial_import_only_once(self, refresh):
        account = self.account(
            setup_step="categories", custom_properties={"enable_vod": True}
        )
        self.group(account)
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        for _ in range(2):
            response = self.action(account, "complete")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["setup_step"], "")
        refresh.assert_called_once()
        options = refresh.call_args.kwargs
        self.assertEqual(options["args"], (account.id,))
        self.assertEqual(options["kwargs"], {"include_vod": False})
        callback = options["link"]
        self.assertEqual(callback.task, "apps.vod.tasks.refresh_vod_content")
        self.assertEqual(callback.args, (account.id,))
        self.assertTrue(callback.immutable)

    @patch("apps.vod.tasks.refresh_vod_content.delay")
    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_vod_only_selection_imports_without_an_empty_live_refresh(
        self, live, vod
    ):
        account = self.account(
            setup_step="categories", status=M3UAccount.Status.PENDING_SETUP,
            custom_properties={"enable_vod": True},
        )
        group = self.group(account)
        group.enabled = False
        group.save(update_fields=["enabled"])
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        for _ in range(2):
            response = self.action(account, "complete")
            self.assertEqual(response.status_code, 200, response.data)
        live.assert_not_called()
        vod.assert_called_once_with(account.id)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "")
        self.assertEqual(account.status, M3UAccount.Status.IDLE)
        self.assertEqual(account.last_message, "")

    @patch("apps.m3u.tasks.refresh_single_m3u_account.apply_async")
    def test_failed_vod_only_dispatch_keeps_the_reviewed_selection_retryable(
        self, live
    ):
        account = self.account(
            setup_step="categories", custom_properties={"enable_vod": True},
        )
        group = self.group(account)
        group.enabled = False
        group.save(update_fields=["enabled"])
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        with patch(
            "apps.vod.tasks.refresh_vod_content.delay",
            side_effect=RuntimeError("broker unavailable"),
        ):
            with (
                self.assertRaises(APIException),
                self.captureOnCommitCallbacks(execute=True),
            ):
                advance_account_setup(account.id, "complete")
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "categories")
        self.assertTrue(account.custom_properties["setup_categories_reviewed"])
        with patch("apps.vod.tasks.refresh_vod_content.delay") as vod:
            self.assertEqual(self.action(account, "complete").status_code, 200)
            vod.assert_called_once_with(account.id)
        live.assert_not_called()

    @patch(
        "apps.m3u.tasks.refresh_single_m3u_account.delay",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_failed_import_dispatch_restores_category_step(self, refresh):
        account = self.account(setup_step="categories", refresh_interval=24)
        self.group(account)
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        with (
            self.assertRaises(APIException),
            self.captureOnCommitCallbacks(execute=True),
        ):
            advance_account_setup(account.id, "complete")
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "categories")
        self.assertFalse(account.refresh_task.enabled)
        self.assertTrue(account.custom_properties["setup_categories_reviewed"])

    @patch(
        "apps.m3u.tasks.refresh_single_m3u_account.apply_async",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_failed_combined_dispatch_restores_category_step(self, refresh):
        account = self.account(
            setup_step="categories", custom_properties={"enable_vod": True},
        )
        self.group(account)
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        with (
            self.assertRaises(APIException),
            self.captureOnCommitCallbacks(execute=True),
        ):
            advance_account_setup(account.id, "complete")
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "categories")
        self.assertTrue(account.custom_properties["setup_categories_reviewed"])
        refresh.assert_called_once()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.delay")
    def test_selection_review_persists_with_no_enabled_groups(self, refresh):
        account = self.account(setup_step="categories")
        group = self.group(account)
        group.enabled = False
        group.save(update_fields=["enabled"])
        self.assertEqual(self.action(account, "complete").status_code, 400)
        for _ in range(2):
            response = self.action(account, "confirm_categories")
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["setup_categories_reviewed"])
            self.assertEqual(response.data["setup_step"], "categories")
        refresh.assert_not_called()
        self.action(account, "back_to_epg")
        self.action(account, "continue_categories")
        response = self.client.get(f"/api/m3u/accounts/{account.id}/")
        self.assertTrue(response.data["setup_categories_reviewed"])
        self.assertFalse(response.data["channel_groups"][0]["enabled"])
        self.assertEqual(self.action(account, "complete").status_code, 200)
        refresh.assert_called_once_with(account.id, include_vod=False)

    def test_selection_review_cannot_be_set_by_generic_account_edits(self):
        account = self.account(setup_step="categories")
        self.group(account)
        response = self.client.patch(
            f"/api/m3u/accounts/{account.id}/",
            {
                "setup_categories_reviewed": True,
                "custom_properties": {"setup_categories_reviewed": True},
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["setup_categories_reviewed"])

    def test_review_requires_loaded_categories_and_retry_resets_it(self):
        account = self.account(setup_step="epg")
        self.assertEqual(self.action(account, "confirm_categories").status_code, 400)
        self.action(account, "continue_categories")
        self.assertEqual(self.action(account, "confirm_categories").status_code, 400)
        self.group(account)
        self.assertEqual(self.action(account, "confirm_categories").status_code, 200)
        response = self.action(account, "retry_categories")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["setup_categories_reviewed"])
        self.assertEqual(self.action(account, "confirm_categories").status_code, 400)

    def test_completion_requires_epg_decision_and_loaded_categories(self):
        account = self.account()
        self.assertEqual(self.action(account, "complete").status_code, 400)
        self.action(account, "skip_epg")
        self.assertEqual(self.action(account, "complete").status_code, 400)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "categories")

    @patch("apps.m3u.tasks.prepare_account_setup.delay")
    def test_retry_requests_discovery_not_another_account(self, refresh):
        account = self.account(setup_step="categories", status="error")
        response = self.action(account, "retry_categories")
        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with(account.id)
        self.assertEqual(response.data["setup_step"], "categories")
        self.assertEqual(response.data["status"], "fetching")

    @patch(
        "apps.m3u.tasks.prepare_account_setup.delay",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_failed_dispatch_returns_created_account(self, dispatch):
        response = self.client.post(
            "/api/m3u/accounts/",
            {"name": "Saved despite broker failure", "account_type": "XC",
             "server_url": "https://example.invalid", "username": "example",
             "password": "example", "start_setup": True},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["setup_step"], "epg")
        self.assertEqual(response.data["status"], "error")
        self.assertEqual(
            M3UAccount.objects.filter(name=response.data["name"]).count(), 1
        )

    @patch("apps.vod.tasks.refresh_categories", return_value=({}, {}))
    @patch("apps.m3u.tasks.refresh_m3u_groups", return_value=([], {"Example": {}}))
    def test_discovery_loads_live_and_vod_categories_without_importing(self, live, vod):
        account = self.account(custom_properties={"enable_vod": True})
        with patch("apps.m3u.tasks.send_m3u_update") as notify:
            discover_setup_categories(account.id)
        self.assertEqual(notify.call_args.kwargs["status"], "pending_setup")
        live.assert_called_once_with(account.id, full_refresh=True)
        vod.assert_called_once_with(account.id)
        account.refresh_from_db()
        self.assertEqual(account.status, "pending_setup")
        self.assertEqual(account.setup_step, "epg")

    @patch("apps.vod.tasks.refresh_categories", return_value=None)
    @patch("apps.m3u.tasks.refresh_m3u_groups", return_value=([], {"Example": {}}))
    def test_partial_discovery_failure_keeps_setup_resumable(self, live, vod):
        account = self.account(
            setup_step="categories", custom_properties={"enable_vod": True}
        )
        with patch("apps.m3u.tasks.send_m3u_update") as notify:
            discover_setup_categories(account.id)
        self.assertEqual(notify.call_args.kwargs["status"], "error")
        account.refresh_from_db()
        self.assertEqual(account.status, "error")
        self.assertEqual(account.setup_step, "categories")

    def test_unfinished_discovery_cannot_complete_using_partial_groups(self):
        account = self.account(setup_step="categories", status="fetching")
        self.group(account)
        self.assertEqual(self.action(account, "complete").status_code, 400)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "categories")

    @patch("core.utils.is_task_lock_held", return_value=False)
    @patch("apps.m3u.tasks.prepare_account_setup.delay")
    def test_stale_fetching_status_can_be_retried(self, dispatch, held):
        account = self.account(setup_step="categories", status="fetching")
        self.assertEqual(self.action(account, "retry_categories").status_code, 200)
        dispatch.assert_called_once_with(account.id)

    @patch("core.utils.is_task_lock_held", return_value=True)
    @patch("apps.m3u.tasks.prepare_account_setup.delay")
    def test_retry_does_not_duplicate_running_discovery(self, dispatch, held):
        account = self.account(setup_step="categories", status="fetching")
        self.assertEqual(self.action(account, "retry_categories").status_code, 200)
        dispatch.assert_not_called()

    def test_setup_action_is_described_in_openapi(self):
        from drf_spectacular.generators import SchemaGenerator

        schema = SchemaGenerator().get_schema(public=True)
        operation = schema["paths"]["/api/m3u/accounts/{id}/setup/"]["post"]
        self.assertIn("requestBody", operation)
        self.assertIn("200", operation["responses"])
        epg = schema["paths"]["/api/m3u/accounts/{id}/epg/"]
        for method in ("get", "post"):
            self.assertIn("200", epg[method]["responses"])

    @patch("apps.epg.signals.refresh_epg_data.delay")
    def test_epg_can_be_added_after_setup_without_restarting_it(self, refresh):
        account = self.account(setup_step="")
        path = f"/api/m3u/accounts/{account.id}/epg/"
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            "source": None, "can_create": True, "other_sources": [],
        })
        self.assertFalse(EPGSource.objects.exists())
        for _ in range(2):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(path, {}, format="json")
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(EPGSource.objects.count(), 1)
        self.assertEqual(
            set(response.data["source"]), {
                "id", "name", "is_active", "status", "source_type", "updated_at",
                "epg_data_count",
            }
        )
        self.assertFalse(response.data["can_create"])
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "")
        refresh.assert_called_once_with(EPGSource.objects.get().id)

    def test_matching_epg_read_is_credential_free_and_survives_renames(self):
        account = self.account()
        self.action(account, "create_epg")
        source = EPGSource.objects.get()
        source.name = "Renamed XMLTV guide"
        source.save(update_fields=["name"])
        path = f"/api/m3u/accounts/{account.id}/epg/"
        response = self.client.get(path)
        self.assertEqual(response.data["source"]["id"], source.id)
        self.assertEqual(response.data["source"]["name"], source.name)
        self.assertNotIn(account.username, str(response.data))
        self.assertNotIn(account.password, str(response.data))
        self.assertNotIn("url", response.data["source"])
        response = self.client.post(path, {}, format="json")
        self.assertEqual(response.data["source"]["id"], source.id)
        self.assertEqual(EPGSource.objects.count(), 1)

    def test_matching_epg_count_uses_saved_channels_not_programmes(self):
        account = self.account()
        path = f"/api/m3u/accounts/{account.id}/epg/"
        created = self.client.post(path, {}, format="json")
        self.assertEqual(created.data["source"]["epg_data_count"], 0)
        source = EPGSource.objects.get(pk=created.data["source"]["id"])
        EPGData.objects.bulk_create([
            EPGData(
                epg_source=source, tvg_id=f"test-{index}",
                name=f"Channel {index}",
            )
            for index in range(3)
        ])
        responses = (
            self.client.get(path), self.client.post(path, {}, format="json"),
        )
        for response in responses:
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["source"]["epg_data_count"], 3)
        source.epgs.all().delete()
        self.assertEqual(self.client.get(path).data["source"]["epg_data_count"], 0)

    def test_standard_accounts_cannot_use_automatic_epg_creation(self):
        account = self.account(account_type="STD", setup_step="categories")
        path = f"/api/m3u/accounts/{account.id}/epg/"
        self.assertEqual(self.client.get(path).data, {
            "source": None, "can_create": False, "other_sources": [],
        })
        self.assertEqual(self.client.post(path, {}, format="json").status_code, 400)
        self.assertFalse(EPGSource.objects.exists())

    def test_epg_creation_requires_a_complete_saved_connection(self):
        for field in ("server_url", "username", "password"):
            account = self.account(name=f"Missing {field}", **{field: ""})
            path = f"/api/m3u/accounts/{account.id}/epg/"
            self.assertEqual(self.client.get(path).data, {
                "source": None, "can_create": False, "other_sources": [],
            })
            self.assertEqual(self.client.post(path, {}, format="json").status_code, 400)
        self.assertFalse(EPGSource.objects.exists())

    def test_epg_creation_and_continuing_are_separate_idempotent_actions(self):
        account = self.account()
        path = f"/api/m3u/accounts/{account.id}/epg/"
        for _ in range(2):
            self.assertEqual(self.client.post(path, {}, format="json").status_code, 200)
        account.refresh_from_db()
        self.assertEqual(account.setup_step, "epg")
        self.assertEqual(EPGSource.objects.count(), 1)
        for _ in range(2):
            response = self.action(account, "continue_categories")
            self.assertEqual(response.data["setup_step"], "categories")
        self.assertEqual(EPGSource.objects.count(), 1)

    def test_epg_step_can_continue_without_creating_a_source(self):
        account = self.account()
        response = self.action(account, "continue_categories")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["setup_step"], "categories")
        self.assertFalse(EPGSource.objects.exists())

    def test_matching_epg_actions_require_admin(self):
        account = self.account()
        viewer = get_user_model().objects.create_user(
            username="epg-viewer", user_level=1
        )
        self.client.force_authenticate(viewer)
        path = f"/api/m3u/accounts/{account.id}/epg/"
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post(path, {}, format="json").status_code, 403)
        self.assertFalse(EPGSource.objects.exists())

    def test_epg_overview_lists_only_safe_metadata_and_excludes_the_matching_source(self):
        account = self.account()
        other = EPGSource.objects.create(
            name="Other guide", source_type="xmltv", is_active=False,
            url="https://other.example.invalid/xmltv?token=private-test-token",
            username="private-test-user", password="private-test-password",
        )
        path = f"/api/m3u/accounts/{account.id}/epg/"
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIsNone(response.data["source"])
        self.assertEqual(response.data["other_sources"][0]["id"], other.id)
        self.assertFalse(response.data["other_sources"][0]["is_active"])
        created = self.client.post(path, {}, format="json")
        self.assertEqual(created.status_code, 200, created.data)
        for result in (created, self.client.get(path)):
            self.assertEqual(
                [row["id"] for row in result.data["other_sources"]], [other.id]
            )
            self.assertNotIn(result.data["source"]["id"], [other.id])
            for row in [result.data["source"], *result.data["other_sources"]]:
                expected = {
                    "id", "name", "is_active", "status", "source_type", "updated_at",
                }
                if row["id"] == result.data["source"]["id"]:
                    expected.add("epg_data_count")
                self.assertEqual(set(row), expected)
            self.assertNotIn("private-test", str(result.data))
            self.assertNotIn(account.username, str(result.data))
            self.assertNotIn(account.password, str(result.data))

    @patch("apps.m3u.api_views.refresh_single_m3u_account.delay")
    @patch("apps.vod.tasks.refresh_vod_content.delay")
    def test_unfinished_setup_blocks_manual_live_and_vod_refresh(self, vod, live):
        for step in M3UAccount.SetupStep.values:
            account = self.account(
                name=f"Pending {step}", setup_step=step,
                custom_properties={"enable_vod": True},
            )
            for path in (
                f"/api/m3u/refresh/{account.id}/",
                f"/api/m3u/accounts/{account.id}/refresh-vod/",
            ):
                response = self.client.post(path, {}, format="json")
                self.assertEqual(response.status_code, 409, response.data)
                self.assertIn("Continue setup", response.data["detail"])
            account.refresh_from_db()
            self.assertEqual(account.setup_step, step)
        live.assert_not_called()
        vod.assert_not_called()

    @patch("apps.m3u.tasks.refresh_single_m3u_account.delay")
    def test_bulk_refresh_skips_unfinished_accounts(self, refresh):
        from apps.m3u.tasks import refresh_m3u_accounts

        pending = self.account(name="Pending", setup_step="categories")
        complete = self.account(name="Complete", setup_step="")
        refresh_m3u_accounts()
        called_ids = [call.args[0] for call in refresh.call_args_list]
        self.assertIn(complete.id, called_ids)
        self.assertNotIn(pending.id, called_ids)

    def test_standard_user_cannot_advance_setup(self):
        account = self.account()
        viewer = get_user_model().objects.create_user(
            username="setup-viewer", user_level=1
        )
        self.client.force_authenticate(viewer)
        self.assertEqual(self.action(account, "create_epg").status_code, 403)
        self.assertFalse(EPGSource.objects.exists())

    def test_legacy_accounts_are_not_enrolled_by_setup_requests(self):
        account = self.account(setup_step="")
        response = self.action(account, "create_epg")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["setup_step"], "")
        self.assertFalse(EPGSource.objects.exists())
