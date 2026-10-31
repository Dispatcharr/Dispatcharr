"""Run-specific cleanup, honest lookup outcomes and checked credentials."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.vod import library
from apps.vod.library_connection import check_connection
from apps.vod.models import VODMetadataState
from apps.vod.tmdb import TMDBAuthenticationError, TMDBError
from core.models import CoreSettings

from . import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class LibraryRunOptionsTests(TestCase):
    setUp = fixtures.LibraryTests.setUp
    endpoint = fixtures.LibraryTests.endpoint
    selection = fixtures.LibraryTests.selection
    metadata = fixtures.LibraryTests.metadata

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_skipped_search_is_not_not_found_or_newly_locked(self, _publish):
        library.save_library_settings({"api_token": "synthetic"})
        for protected in (False, True):
            self.movie.tmdb_lookup_excluded = protected
            self.movie.save()
            state = library.queue_library_job(
                "enrich", [("movie", self.movie.pk)], include_protected=protected
            )
            with patch("apps.vod.library.tmdb_client") as client:
                library.run_library_job(state["task_id"])
                client.assert_not_called()
            self.movie.refresh_from_db()
            self.assertEqual(self.movie.tmdb_status, "not_checked")
            self.assertEqual(
                self.movie.tmdb_metadata["_lookup_skip_reason"], "search_disabled"
            )
            self.assertEqual(self.movie.tmdb_lookup_excluded, protected)
            state = VODMetadataState.objects.get(pk=1)
            self.assertEqual(
                (state.progress["skipped"], state.progress["not_found"]), (1, 0)
            )

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_enabling_search_makes_only_search_disabled_titles_eligible(
        self, _publish
    ):
        library.save_library_settings({"api_token": "synthetic"})
        state = library.queue_library_job("enrich", [("movie", self.movie.pk)])
        with patch("apps.vod.library.tmdb_client"):
            library.run_library_job(state["task_id"])
        pending = {
            "all_matching": True,
            "filters": {"locked": "false", "metadata_status": "pending_lookup"},
        }
        self.assertEqual(library.selected_content(pending), [])
        library.save_library_settings({"match_missing": True})
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.tmdb_status, "")
        self.assertEqual(library.selected_content(pending), [["movie", self.movie.pk]])

    def test_automatic_lookup_skips_unchanged_unsuccessful_titles(self):
        pending = {
            "all_matching": True,
            "filters": {"locked": "false", "metadata_status": "pending_lookup"},
        }
        for status, eligible in (
            ("", True),
            ("failed", True),
            ("not_found", False),
            ("ambiguous", False),
            ("not_checked", False),
            ("matched", False),
        ):
            with self.subTest(status=status):
                self.movie.tmdb_status = status
                self.movie.save()
                self.assertEqual(bool(library.selected_content(pending)), eligible)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_missing_year_does_not_trigger_an_unsafe_search_or_lock(self, _publish):
        library.save_library_settings({"api_token": "synthetic", "match_missing": True})
        self.movie.name, self.movie.year = "Film", None
        self.movie.save()
        self.source.custom_properties = {"basic_data": {"name": "Film"}}
        self.source.save()
        state = library.queue_library_job("enrich", [("movie", self.movie.pk)])
        with patch("apps.vod.library.tmdb_client") as client:
            library.run_library_job(state["task_id"])
            client.assert_not_called()
        self.movie.refresh_from_db()
        self.assertEqual(
            self.movie.tmdb_metadata["_lookup_skip_reason"], "year_missing"
        )
        self.assertFalse(self.movie.tmdb_lookup_excluded)

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_confirmed_options_are_snapshotted_without_changing_settings(
        self, _publish
    ):
        library.save_library_settings({"api_token": "synthetic"})
        rules = [{"value": "NF -", "enabled": True}]
        response = self.client.post(
            self.endpoint("bulk"),
            self.selection(operation="enrich", search_missing=True, title_rules=rules),
            format="json",
        )
        self.assertEqual(response.status_code, 202, response.data)
        self.assertFalse(library.library_settings()["match_missing"])
        self.assertEqual(library.library_settings()["title_rules"], [])
        self.assertNotIn("synthetic", str(response.data))
        library.save_library_settings({"title_rules": ["different"]})
        with patch("apps.vod.library.tmdb_client") as client:
            client.return_value.search_outcome.return_value = ("123", "matched", 1)
            client.return_value.details.return_value = self.metadata()
            library.run_library_job(response.data["state"]["task_id"])
            client.return_value.search_outcome.assert_called_once_with(
                "Film", 2020, "movie", ["en-US"]
            )
        self.movie.refresh_from_db()
        self.assertTrue(self.movie.tmdb_lookup_excluded)
        self.assertEqual(self.movie.tmdb_status, "matched")

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_cleanup_and_resume_keep_the_confirmed_rules_and_protect_titles(
        self, _publish
    ):
        state = library.queue_library_job(
            "cleanup",
            [("movie", self.movie.pk)],
            job_settings={"title_rules": ["NF -"]},
        )
        VODMetadataState.objects.filter(pk=1).update(status="cancelled")
        response = self.client.post(self.endpoint("resume-job"), {}, format="json")
        self.assertEqual(response.status_code, 202, response.data)
        library.run_library_job(response.data["task_id"])
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.clean_title, "Film")
        self.assertTrue(self.movie.tmdb_lookup_excluded)
        self.assertNotEqual(state["task_id"], response.data["task_id"])

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_real_lookup_failure_is_not_classified_as_skipped_or_protected(
        self, _publish
    ):
        library.save_library_settings({"api_token": "synthetic", "match_missing": True})
        for outcome in ("not_found", "ambiguous"):
            self.movie.tmdb_lookup_excluded = False
            self.movie.save()
            state = library.queue_library_job("enrich", [("movie", self.movie.pk)])
            with patch("apps.vod.library.tmdb_client") as client:
                client.return_value.search_outcome.return_value = ("", outcome, 0)
                library.run_library_job(state["task_id"])
            self.movie.refresh_from_db()
            self.assertEqual(self.movie.tmdb_status, outcome)
            self.assertFalse(self.movie.tmdb_lookup_excluded)
            self.assertNotIn("_lookup_skip_reason", self.movie.tmdb_metadata)
            self.assertEqual(
                self.movie.tmdb_metadata["_lookup_key"],
                [self.movie.clean_title, self.movie.year],
            )

    @patch("apps.vod.tasks.enrich_vod_library.apply_async")
    def test_effective_manual_ids_are_used_and_manual_edits_remain_protected(
        self, _publish
    ):
        library.save_library_settings({"api_token": "synthetic"})
        self.movie.tmdb_match_id = "123"
        self.movie.save()
        state = library.queue_library_job("enrich", [("movie", self.movie.pk)])
        with patch("apps.vod.library.tmdb_client") as client:
            client.return_value.details.return_value = self.metadata()
            library.run_library_job(state["task_id"])
            client.return_value.search_outcome.assert_not_called()
            self.assertEqual(client.return_value.details.call_args.args[0], "123")
        library.apply_tmdb(self.movie, self.metadata())
        self.movie.refresh_from_db()
        self.assertTrue(self.movie.tmdb_lookup_excluded)

    @patch("apps.vod.library_connection.Client.validate")
    def test_connection_status_is_verified_secret_free_and_invalidated_on_rotation(
        self, validate
    ):
        library.save_library_settings({"api_token": "synthetic"})
        self.assertEqual(
            library.library_settings()["connection"]["status"], "unchecked"
        )
        response = self.client.post(self.endpoint("test-connection"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "connected")
        validate.assert_called_once()
        settings = self.client.get(self.endpoint("settings")).data
        self.assertEqual(settings["connection"]["status"], "connected")
        self.assertNotIn("synthetic", str(settings))
        self.assertNotIn("credential", str(settings))
        library.save_library_settings({"api_token": "rotated"})
        self.assertEqual(
            library.library_settings()["connection"]["status"], "unchecked"
        )

    @patch("apps.vod.library_connection.Client.validate")
    def test_draft_test_does_not_save_a_token_or_settings(self, _validate):
        before = list(CoreSettings.objects.values())
        response = self.client.post(
            self.endpoint("test-connection"), {"api_token": "draft"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(before, list(CoreSettings.objects.values()))

    @patch(
        "apps.vod.library_connection.Client.validate",
        side_effect=TMDBAuthenticationError("secret"),
    )
    def test_bad_token_save_keeps_the_working_credential(self, _validate):
        library.save_library_settings({"api_token": "working"})
        response = self.client.put(
            self.endpoint("settings"), {"api_token": "bad"}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("api_token", response.data)
        self.assertEqual(library.library_settings(private=True)["api_token"], "working")
        self.assertNotIn("secret", str(response.data))

    @patch(
        "apps.vod.library_connection.Client.validate",
        side_effect=TMDBError("private-url"),
    )
    def test_network_failure_is_not_reported_as_invalid_authentication(self, _validate):
        result = check_connection("synthetic")
        self.assertEqual(result["status"], "error")
        self.assertIn("could not be reached", result["detail"])
        self.assertNotIn("private-url", str(result))

    @patch.dict("os.environ", {"TMDB_API_READ_ACCESS_TOKEN": "environment-token"})
    @patch("apps.vod.library_connection.Client.validate")
    def test_environment_credential_can_be_checked_but_not_replaced(self, _validate):
        cache.clear()
        response = self.client.post(self.endpoint("test-connection"), {}, format="json")
        self.assertEqual(response.data["status"], "connected")
        self.assertEqual(
            library.library_settings()["connection"]["status"], "connected"
        )
        response = self.client.put(
            self.endpoint("settings"), {"api_token": "override"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_connection_check_is_admin_only(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.endpoint("test-connection"), {"api_token": "draft"}, format="json"
        )
        self.assertEqual(response.status_code, 403)
