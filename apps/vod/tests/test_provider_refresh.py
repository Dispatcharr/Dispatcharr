from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.vod.models import M3UMovieRelation
from apps.vod.provider_refresh import keys, queue_provider_refresh, run_provider_refresh

from . import test_library as fixtures


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class ProviderRefreshTests(TestCase):
    setUp = fixtures.LibraryTests.setUp

    @patch("apps.vod.tasks.refresh_library_provider_details.delay")
    @patch("apps.vod.tasks.refresh_movie_advanced_data")
    def test_http_requests_return_imported_data_and_queue_only_once(
        self, fetch, publish
    ):
        url = f"/api/vod/movies/{self.movie.pk}/provider-info/"
        first = self.client.get(url)
        second = self.client.get(url)
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.json()["refresh_status"], "pending")
        self.assertEqual(second.json()["refresh_status"], "pending")
        self.assertEqual(publish.call_count, 1)
        fetch.assert_not_called()

    @patch("apps.vod.tasks.refresh_library_provider_details.delay")
    def test_worker_updates_status_only_for_its_own_lock(self, publish):
        queue_provider_refresh("movie", self.source.pk, required=True)
        token = publish.call_args.args[2]

        def fetched(*args, **kwargs):
            M3UMovieRelation.objects.filter(pk=self.source.pk).update(
                last_advanced_refresh=timezone.now(),
                custom_properties={"detailed_fetched": True},
            )

        with patch("apps.vod.tasks.refresh_movie_advanced_data", side_effect=fetched):
            self.assertEqual(
                run_provider_refresh("movie", self.source.pk, token), "completed"
            )
        lock, status = keys("movie", self.source.pk)
        self.assertIsNone(cache.get(lock))
        self.assertEqual(cache.get(status)["status"], "completed")
        cache.set(lock, "new-token")
        self.assertEqual(
            run_provider_refresh("movie", self.source.pk, token), "obsolete"
        )
        self.assertEqual(cache.get(lock), "new-token")

    @patch(
        "apps.vod.tasks.refresh_library_provider_details.delay",
        side_effect=RuntimeError("broker unavailable"),
    )
    def test_publish_failure_is_visible_and_explicit_retry_is_possible(self, publish):
        self.assertEqual(
            queue_provider_refresh("movie", self.source.pk, required=True), "failed"
        )
        self.assertEqual(
            queue_provider_refresh("movie", self.source.pk, required=True), "failed"
        )
        self.assertEqual(publish.call_count, 1)
        publish.side_effect = None
        self.assertEqual(
            queue_provider_refresh("movie", self.source.pk, required=True, force=True),
            "pending",
        )

    @patch("apps.vod.tasks.refresh_library_provider_details.delay")
    @patch("apps.vod.tasks.refresh_movie_advanced_data")
    def test_inactive_sources_are_not_contacted_and_failed_fetches_keep_existing_data(
        self, fetch, publish
    ):
        queue_provider_refresh("movie", self.source.pk, required=True)
        token = publish.call_args.args[2]
        self.account.is_active = False
        self.account.save()
        self.assertEqual(
            run_provider_refresh("movie", self.source.pk, token), "unavailable"
        )
        fetch.assert_not_called()
        self.account.is_active = True
        self.account.save()
        queue_provider_refresh("movie", self.source.pk, required=True, force=True)
        token = publish.call_args.args[2]
        self.assertEqual(run_provider_refresh("movie", self.source.pk, token), "failed")
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.name, "NF - Film (2020)")
