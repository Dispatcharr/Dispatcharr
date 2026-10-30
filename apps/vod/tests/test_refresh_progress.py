from unittest.mock import Mock, patch

from django.test import TestCase

from apps.m3u.models import M3UAccount
from apps.vod.refresh_progress import VODRefreshProgress
from apps.vod.tasks import refresh_movies, refresh_series


class VODRefreshProgressTests(TestCase):
    @patch("apps.m3u.tasks.send_m3u_update")
    @patch("apps.vod.refresh_progress.time.monotonic", side_effect=[100, 110])
    def test_reports_coarse_counts_and_elapsed_time(self, clock, send):
        VODRefreshProgress(7).send("Processing movies", 20, processed=1000, total=5000)
        send.assert_called_once_with(
            7,
            "vod_refresh",
            20,
            status="processing",
            message="VOD refresh: Processing movies",
            phase="Processing movies",
            elapsed_time=10,
            time_remaining=40,
            items_processed=1000,
            items_total=5000,
            provider_items_total=5000,
        )

    @patch("apps.m3u.tasks.send_m3u_update")
    def test_never_marks_progress_complete_before_the_task_finishes(self, send):
        VODRefreshProgress(7).send("Cleanup", 100)
        self.assertEqual(send.call_args.args[2], 99)

    @patch("apps.m3u.tasks.send_m3u_update", side_effect=RuntimeError("Disconnected"))
    def test_reporting_failure_does_not_abort_import(self, send):
        with self.assertLogs("apps.vod.refresh_progress", level="WARNING"):
            VODRefreshProgress(7).send("Processing movies", 20)

    def test_movie_and_series_chunks_report_only_after_processing(self):
        account = M3UAccount.objects.create(name="Progress test", account_type="XC")
        for refresh, fetch, process, phase, end in (
            (
                refresh_movies,
                "get_vod_streams",
                "process_movie_batch",
                "Processing movies",
                55,
            ),
            (
                refresh_series,
                "get_series",
                "process_series_batch",
                "Processing series",
                90,
            ),
        ):
            with self.subTest(phase=phase):
                client = Mock()
                getattr(client, fetch).return_value = [{"name": "Title"}] * 2500
                progress = Mock()
                with patch(f"apps.vod.tasks.{process}") as batch:
                    result = refresh(client, account, {}, {}, progress=progress)
                self.assertEqual(result, 2500)
                self.assertEqual(
                    [len(call.args[1]) for call in batch.call_args_list],
                    [1000, 1000, 500],
                )
                events = [
                    call
                    for call in progress.send.call_args_list
                    if call.args[0] == phase
                ]
                self.assertEqual(
                    [call.kwargs["processed"] for call in events], [1000, 2000, 2500]
                )
                self.assertEqual(events[-1].args[1], end)
                self.assertTrue(all(call.kwargs["total"] == 2500 for call in events))

    def test_empty_catalogs_do_not_divide_by_zero(self):
        account = M3UAccount.objects.create(
            name="Empty progress test", account_type="XC"
        )
        client = Mock()
        client.get_vod_streams.return_value = []
        client.get_series.return_value = []
        for refresh in (refresh_movies, refresh_series):
            progress = Mock()
            self.assertEqual(refresh(client, account, {}, {}, progress=progress), 0)
            self.assertEqual(
                progress.send.call_args.kwargs, {"processed": 0, "total": 0}
            )

    def test_failed_batch_does_not_advance_progress(self):
        account = M3UAccount.objects.create(
            name="Failed progress test", account_type="XC"
        )
        client = Mock()
        client.get_vod_streams.return_value = [{"name": "Title"}]
        progress = Mock()
        with patch(
            "apps.vod.tasks.process_movie_batch",
            side_effect=RuntimeError("Failed batch"),
        ):
            with self.assertRaises(RuntimeError):
                refresh_movies(client, account, {}, {}, progress=progress)
        self.assertEqual(progress.send.call_args.args[0], "Fetching movies")
