from django.test import SimpleTestCase

from apps.epg.tasks import (
    _CHANNEL_PARSE_PROGRESS_CAP,
    _CHANNEL_PARSE_PROGRESS_START,
    _channel_parse_progress,
)


class ChannelParseProgressTests(SimpleTestCase):
    def test_exceeding_estimate_recalculates_instead_of_going_over_cap(self):
        """101/100 used to yield ~90%+; now bumps estimate to 101 so ratio stays <= 1."""
        progress, estimate = _channel_parse_progress(100, 100, had_db_baseline=True)
        self.assertEqual(estimate, 100)
        self.assertLessEqual(progress, _CHANNEL_PARSE_PROGRESS_CAP)

        progress, estimate = _channel_parse_progress(101, 100, had_db_baseline=True)
        self.assertEqual(estimate, 101)
        self.assertLessEqual(progress, _CHANNEL_PARSE_PROGRESS_CAP)
        self.assertGreater(progress, 90)

    def test_large_xml_growth_never_exceeds_cap(self):
        """Previously 425 channels vs DB estimate of 100 could show ~300%."""
        estimate = 100
        for processed in (100, 200, 300, 425):
            progress, estimate = _channel_parse_progress(
                processed, estimate, had_db_baseline=True
            )
            self.assertLessEqual(progress, _CHANNEL_PARSE_PROGRESS_CAP)

    def test_first_import_crawls_instead_of_flat_ninety(self):
        progress, estimate = _channel_parse_progress(100, 0, had_db_baseline=False)
        self.assertEqual(estimate, 0)
        self.assertEqual(progress, _CHANNEL_PARSE_PROGRESS_START + 1)
        self.assertLess(progress, 90)

        progress, _ = _channel_parse_progress(5000, 0, had_db_baseline=False)
        self.assertLess(progress, _CHANNEL_PARSE_PROGRESS_CAP)

    def test_partial_progress_when_below_estimate(self):
        progress, estimate = _channel_parse_progress(50, 100, had_db_baseline=True)
        self.assertEqual(estimate, 100)
        self.assertGreater(progress, _CHANNEL_PARSE_PROGRESS_START)
        self.assertLess(progress, _CHANNEL_PARSE_PROGRESS_CAP)
