"""Offer the Library once after an account's first successful nonempty import."""

from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.m3u.models import M3UAccount
from apps.m3u.refresh_metrics import record_refresh_metrics
from apps.vod.models import M3UMovieRelation, Movie
from apps.vod.tasks import _refresh_vod_content_impl


class FirstLibraryImportTests(TestCase):
    def setUp(self):
        self.account = M3UAccount.objects.create(
            name="First Library import",
            account_type="XC",
            custom_properties={"enable_vod": True},
        )

    def complete(self, selected):
        return record_refresh_metrics(
            self.account.pk,
            "vod",
            {
                "movies": {"provider_total": 5, "selected_total": selected},
                "series": {"provider_total": 0, "selected_total": 0},
            },
            1,
            timezone.now(),
        )

    def test_only_first_nonempty_success_offers_library(self):
        self.assertFalse(self.complete(0))
        self.assertTrue(self.complete(1))
        self.account.refresh_from_db()
        first = self.account.custom_properties["refresh_timings"][
            "vod_first_imported_at"
        ]
        self.assertFalse(self.complete(2))
        self.assertFalse(self.complete(0))
        self.assertFalse(self.complete(1))
        self.account.refresh_from_db()
        self.assertEqual(
            self.account.custom_properties["refresh_timings"]["vod_first_imported_at"],
            first,
        )
        self.assertTrue(self.account.custom_properties["enable_vod"])

    def test_existing_successful_imports_are_not_treated_as_new_accounts(self):
        previous = timezone.now().isoformat()
        M3UAccount.objects.filter(pk=self.account.pk).update(
            custom_properties={
                "enable_vod": True,
                "refresh_timings": {"vod_completed_at": previous},
                "vod_catalog_counts": {"movies": {"selected_total": 3}},
            }
        )
        self.assertFalse(self.complete(2))
        self.account.refresh_from_db()
        self.assertEqual(
            self.account.custom_properties["refresh_timings"]["vod_first_imported_at"],
            previous,
        )

    def test_a_series_only_import_also_offers_the_library(self):
        self.assertTrue(
            record_refresh_metrics(
                self.account.pk,
                "vod",
                {"movies": {"selected_total": 0}, "series": {"selected_total": 1}},
                1,
                timezone.now(),
            )
        )

    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.vod.tasks.cleanup_orphaned_vod_content")
    @patch("apps.vod.tasks.refresh_series", return_value=0)
    @patch("apps.vod.tasks.refresh_movies")
    @patch("apps.vod.tasks.refresh_categories", return_value=({}, {}))
    @patch("apps.vod.tasks.XtreamCodesClient")
    def test_refresh_attaches_the_action_only_to_the_first_success(
        self, client, categories, movies, series, cleanup, notify
    ):
        movie = Movie.objects.create(name="Imported movie")

        def import_movie(*args, **kwargs):
            M3UMovieRelation.objects.update_or_create(
                m3u_account=self.account,
                movie=movie,
                stream_id="first",
                defaults={"last_seen": timezone.now()},
            )
            return 1

        movies.side_effect = import_movie
        for expected in (True, False):
            self.assertIn("completed", _refresh_vod_content_impl(self.account.pk))
            complete = [
                call
                for call in notify.call_args_list
                if call.kwargs.get("status") == "success"
            ][-1]
            self.assertIs(complete.kwargs["first_vod_import"], expected)

    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.vod.tasks.refresh_categories", return_value=None)
    @patch("apps.vod.tasks.XtreamCodesClient")
    def test_failed_refresh_does_not_consume_the_first_import_action(
        self, client, categories, notify
    ):
        self.assertIn("failed", _refresh_vod_content_impl(self.account.pk))
        self.assertFalse(
            any(call.kwargs.get("first_vod_import") for call in notify.call_args_list)
        )
        self.assertTrue(self.complete(1))

    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.m3u.refresh_metrics.record_refresh_metrics")
    def test_finalization_failure_does_not_record_a_success(self, metrics, notify):
        with (
            patch("apps.vod.tasks.XtreamCodesClient"),
            patch("apps.vod.tasks.refresh_categories", return_value=({}, {})),
            patch("apps.vod.tasks.refresh_movies", return_value=0),
            patch("apps.vod.tasks.refresh_series", return_value=0),
            patch("apps.vod.tasks.cleanup_orphaned_vod_content"),
            patch(
                "apps.vod.provider_metadata.reconcile_provider_metadata",
                side_effect=RuntimeError("Finalization failed"),
            ),
        ):
            self.assertIn("failed", _refresh_vod_content_impl(self.account.pk))
        metrics.assert_not_called()
        self.assertFalse(
            any(call.kwargs.get("first_vod_import") for call in notify.call_args_list)
        )
