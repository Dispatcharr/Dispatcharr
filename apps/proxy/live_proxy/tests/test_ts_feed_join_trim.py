"""join_target cleared when the writer repositions without delivering."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.proxy.live_proxy.output.ts_feed import run_ts_buffer_writer


class TsFeedJoinTargetTests(SimpleTestCase):
    def test_before_poll_rewind_clears_join_target(self):
        chunk = b"unchanged-first-chunk"
        ts_buffer = MagicMock()
        ts_buffer.index = 5
        ts_buffer.resolve_join_position.return_value = (1, 99.0)
        ts_buffer.get_optimized_client_data_indexed.side_effect = [
            ([(2, chunk)], 2),
            ([(3, b"second")], 3),
        ]
        ts_buffer.discontinuities_in_range.return_value = []
        fed = []

        def before_poll(local_index, watcher):
            return 4

        run_ts_buffer_writer(
            is_running=lambda: len(fed) < 2,
            ts_buffer=ts_buffer,
            behind_seconds=6,
            watcher=MagicMock(),
            feed_chunk=lambda data, watcher, chunk_index=None: fed.append(
                (chunk_index, data)
            ) or True,
            on_discontinuity=lambda reason: None,
            before_poll=before_poll,
            sleep_fn=lambda _s: None,
        )

        ts_buffer.prepare_first_join_chunk.assert_not_called()
        self.assertEqual(fed[0][1], chunk)