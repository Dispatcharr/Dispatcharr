"""Tests for `apps.timeshift.helpers` — timestamp shape conversion and URL build."""

from django.test import TestCase

from apps.timeshift.helpers import (
    build_timeshift_candidate_urls,
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    convert_timestamp_to_provider_tz,
    format_timestamp_as_sql_datetime,
    format_timestamp_as_underscore,
)


class _FakeAccount:
    def __init__(self):
        self.server_url = "http://example.test"
        self.username = "user"
        self.password = "pass"


class TimestampFormatTests(TestCase):
    """Timestamp reshape functions change format only — no timezone conversion."""

    def test_format_sql_reshapes_without_tz_conversion(self):
        self.assertEqual(
            format_timestamp_as_sql_datetime("2026-05-12:17-00"),
            "2026-05-12 17:00:00",
        )

    def test_format_sql_accepts_underscore_input(self):
        self.assertEqual(
            format_timestamp_as_sql_datetime("2026-05-12_17-00"),
            "2026-05-12 17:00:00",
        )

    def test_format_sql_invalid_falls_back(self):
        self.assertEqual(format_timestamp_as_sql_datetime("garbage"), "garbage")

    def test_format_underscore_from_colon_dash(self):
        self.assertEqual(
            format_timestamp_as_underscore("2026-05-21:12-55"),
            "2026-05-21_12-55",
        )

    def test_format_underscore_idempotent(self):
        # Underscore input → underscore output (no change)
        self.assertEqual(
            format_timestamp_as_underscore("2026-05-21_12-55"),
            "2026-05-21_12-55",
        )

    def test_format_underscore_invalid_falls_back(self):
        self.assertEqual(format_timestamp_as_underscore("garbage"), "garbage")


class BuildTimeshiftUrlTests(TestCase):
    def setUp(self):
        self.account = _FakeAccount()

    def test_format_a_passes_dash_shape_unchanged(self):
        url = build_timeshift_url_format_a(
            self.account, "22372", "2026-05-12:19-00", 40
        )
        self.assertIn("start=2026-05-12:19-00", url)
        self.assertIn("stream=22372", url)
        self.assertIn("duration=40", url)

    def test_format_a_passes_sql_shape_unchanged(self):
        url = build_timeshift_url_format_a(
            self.account, "22372", "2026-05-12 19:00:00", 40
        )
        self.assertIn("start=2026-05-12 19:00:00", url)

    def test_format_b_path_with_dash_shape(self):
        url = build_timeshift_url_format_b(
            self.account, "22372", "2026-05-12:19-00", 40
        )
        self.assertIn("/40/2026-05-12:19-00/22372.ts", url)


class CandidateOrderingTests(TestCase):
    """`build_timeshift_candidate_urls` must try the PATH form (which seeks the
    archive) before the QUERY form (which returns LIVE on some providers,
    silently ignoring the requested timestamp). Regression guard for the
    "catch-up plays the live stream instead of the requested programme" bug."""

    def setUp(self):
        self.account = _FakeAccount()

    def _is_path_form(self, url):
        return "/timeshift/" in url and url.endswith(".ts") and "timeshift.php" not in url

    def _is_query_form(self, url):
        return "timeshift.php?" in url

    def test_every_path_candidate_precedes_every_query_candidate(self):
        urls = build_timeshift_candidate_urls(self.account, "22372", "2026-05-12:19-00", 40)
        path_indices = [i for i, u in enumerate(urls) if self._is_path_form(u)]
        query_indices = [i for i, u in enumerate(urls) if self._is_query_form(u)]
        # Each URL is classified as exactly one form.
        self.assertEqual(len(path_indices) + len(query_indices), len(urls))
        self.assertTrue(path_indices and query_indices)
        # The last PATH candidate still comes before the first QUERY candidate.
        self.assertLess(max(path_indices), min(query_indices))

    def test_first_candidate_is_path_form_with_canonical_dash_timestamp(self):
        urls = build_timeshift_candidate_urls(self.account, "22372", "2026-05-12:19-00", 40)
        self.assertTrue(self._is_path_form(urls[0]))
        # Canonical colon-dash timestamp, passed through unchanged.
        self.assertIn("/40/2026-05-12:19-00/22372.ts", urls[0])

    def test_accepts_underscore_input_timestamp(self):
        # Client may send the underscore shape; PATH form still leads.
        urls = build_timeshift_candidate_urls(self.account, "22372", "2026-05-12_19-00", 40)
        self.assertTrue(self._is_path_form(urls[0]))


class ConvertTimestampToProviderTzTests(TestCase):
    """`convert_timestamp_to_provider_tz` shifts a UTC catch-up timestamp into the
    serving provider's local zone (XC providers index archives in their own zone),
    DST-correct, and is a no-op when the zone is UTC/unknown/missing."""

    def test_utc_to_brussels_summer_is_plus_two(self):
        # June → CEST (+02:00): 17:00 UTC == 19:00 Brussels (the 19h JT case).
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-06-08:17-00", "Europe/Brussels"),
            "2026-06-08:19-00",
        )

    def test_utc_to_brussels_winter_is_plus_one(self):
        # January → CET (+01:00): 17:00 UTC == 18:00 Brussels (DST handled).
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-01-08:17-00", "Europe/Brussels"),
            "2026-01-08:18-00",
        )

    def test_day_rollover(self):
        # 23:30 UTC + 2h (CEST) crosses midnight into the next day.
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-06-08:23-30", "Europe/Brussels"),
            "2026-06-09:01-30",
        )

    def test_underscore_input_returns_colon_dash(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-06-08_17-00", "Europe/Brussels"),
            "2026-06-08:19-00",
        )

    def test_utc_zone_is_noop(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-06-08:17-00", "UTC"),
            "2026-06-08:17-00",
        )

    def test_none_zone_is_noop(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-06-08:17-00", None),
            "2026-06-08:17-00",
        )

    def test_unknown_zone_is_noop(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("2026-06-08:17-00", "Mars/Phobos"),
            "2026-06-08:17-00",
        )

    def test_garbage_timestamp_passthrough(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("garbage", "Europe/Brussels"),
            "garbage",
        )
