"""Tests for `apps.timeshift.helpers`: timestamp shape conversion and URL build."""

from datetime import datetime, timezone

from django.test import TestCase

from apps.timeshift.helpers import (
    TimeshiftCredentials,
    build_timeshift_candidate_urls,
    build_timeshift_url_format_a,
    build_timeshift_url_format_b,
    convert_timestamp_to_provider_tz,
    format_timestamp_as_colon_dash,
    format_timestamp_as_colon_seconds,
    format_timestamp_as_sql_datetime,
    format_timestamp_as_underscore,
    normalize_catchup_timestamp_input,
    order_catchup_streams_for_timestamp,
    parse_catchup_timestamp,
    programme_age_days,
)


def _make_creds():
    # The builders consume resolved per-profile credentials, never an account
    # object - get_transformed_credentials() produces these in the view.
    return TimeshiftCredentials("http://example.test", "user", "pass")


class TimestampFormatTests(TestCase):
    """Timestamp reshape functions change format only; no timezone conversion."""

    def test_normalize_colon_dash_shape(self):
        self.assertEqual(
            normalize_catchup_timestamp_input("2026-05-21:12-55"),
            "2026-05-21T12:55:00",
        )

    def test_normalize_colon_seconds_xc_format(self):
        self.assertEqual(
            normalize_catchup_timestamp_input("2026-06-23:04:00:00"),
            "2026-06-23T04:00:00",
        )

    def test_normalize_epg_sql_format(self):
        self.assertEqual(
            normalize_catchup_timestamp_input("2026-06-23 04:00:00"),
            "2026-06-23T04:00:00",
        )

    def test_normalize_unix_epoch_seconds(self):
        epoch = str(int(datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(
            normalize_catchup_timestamp_input(epoch),
            "2026-06-23T04:00:00",
        )

    def test_normalize_unix_epoch_milliseconds(self):
        epoch_ms = str(
            int(datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
        )
        self.assertEqual(
            normalize_catchup_timestamp_input(epoch_ms),
            "2026-06-23T04:00:00",
        )

    def test_normalize_iso8601_utc(self):
        self.assertEqual(
            normalize_catchup_timestamp_input("2026-06-23T04:00:00Z"),
            "2026-06-23T04:00:00",
        )

    def test_normalize_iso8601_with_offset(self):
        self.assertEqual(
            normalize_catchup_timestamp_input("2026-06-23T06:00:00+02:00"),
            "2026-06-23T04:00:00",
        )

    def test_normalize_rejects_garbage(self):
        self.assertIsNone(normalize_catchup_timestamp_input("garbage"))
        self.assertIsNone(normalize_catchup_timestamp_input(""))
        self.assertIsNone(normalize_catchup_timestamp_input("12345"))

    def test_parse_rejects_invalid_calendar_date(self):
        self.assertIsNone(parse_catchup_timestamp("2026-13-45:04-00"))

    def test_parse_colon_dash_format(self):
        dt = parse_catchup_timestamp("2026-05-21:12-55")
        self.assertEqual(dt, datetime(2026, 5, 21, 12, 55, 0))

    def test_parse_underscore_format(self):
        dt = parse_catchup_timestamp("2026-05-21_12-55")
        self.assertEqual(dt, datetime(2026, 5, 21, 12, 55, 0))

    def test_parse_colon_minutes_without_seconds(self):
        dt = parse_catchup_timestamp("2026-06-23:04:00")
        self.assertEqual(dt, datetime(2026, 6, 23, 4, 0, 0))

    def test_parse_colon_seconds_xc_format(self):
        dt = parse_catchup_timestamp("2026-06-23:04:00:00")
        self.assertEqual(dt, datetime(2026, 6, 23, 4, 0, 0))

    def test_parse_epg_sql_format(self):
        dt = parse_catchup_timestamp("2026-06-23 04:00:00")
        self.assertEqual(dt, datetime(2026, 6, 23, 4, 0, 0))

    def test_format_colon_dash_from_colon_seconds(self):
        self.assertEqual(
            format_timestamp_as_colon_dash("2026-06-23:04:00:00"),
            "2026-06-23:04-00",
        )

    def test_format_colon_seconds_from_colon_dash(self):
        self.assertEqual(
            format_timestamp_as_colon_seconds("2026-06-23:04-00"),
            "2026-06-23:04:00:00",
        )

    def test_format_colon_seconds_from_unix_epoch(self):
        epoch = str(int(datetime(2026, 6, 23, 4, 0, 0, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(
            format_timestamp_as_colon_dash(epoch),
            "2026-06-23:04-00",
        )

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
        self.creds = _make_creds()

    def test_format_a_passes_dash_shape_unchanged(self):
        url = build_timeshift_url_format_a(
            self.creds, "22372", "2026-05-12:19-00", 40
        )
        self.assertIn("start=2026-05-12:19-00", url)
        self.assertIn("stream=22372", url)
        self.assertIn("duration=40", url)

    def test_format_a_passes_sql_shape_unchanged(self):
        url = build_timeshift_url_format_a(
            self.creds, "22372", "2026-05-12 19:00:00", 40
        )
        self.assertIn("start=2026-05-12 19:00:00", url)

    def test_format_b_path_with_dash_shape(self):
        url = build_timeshift_url_format_b(
            self.creds, "22372", "2026-05-12:19-00", 40
        )
        self.assertIn("/40/2026-05-12:19-00/22372.ts", url)


class CandidateOrderingTests(TestCase):
    """`build_timeshift_candidate_urls` must try the PATH form (which seeks the
    archive) before the QUERY form (which returns LIVE on some providers,
    silently ignoring the requested timestamp). Regression guard for the
    "catch-up plays the live stream instead of the requested programme" bug."""

    def setUp(self):
        self.creds = _make_creds()

    def _is_path_form(self, url):
        return "/timeshift/" in url and url.endswith(".ts") and "timeshift.php" not in url

    def _is_query_form(self, url):
        return "timeshift.php?" in url

    def test_every_path_candidate_precedes_every_query_candidate(self):
        urls = build_timeshift_candidate_urls(self.creds, "22372", "2026-05-12:19-00", 40)
        path_indices = [i for i, u in enumerate(urls) if self._is_path_form(u)]
        query_indices = [i for i, u in enumerate(urls) if self._is_query_form(u)]
        # Each URL is classified as exactly one form.
        self.assertEqual(len(path_indices) + len(query_indices), len(urls))
        self.assertTrue(path_indices and query_indices)
        # The last PATH candidate still comes before the first QUERY candidate.
        self.assertLess(max(path_indices), min(query_indices))

    def test_first_candidate_is_path_form_with_canonical_dash_timestamp(self):
        urls = build_timeshift_candidate_urls(self.creds, "22372", "2026-05-12:19-00", 40)
        self.assertTrue(self._is_path_form(urls[0]))
        # Canonical colon-dash timestamp, passed through unchanged.
        self.assertIn("/40/2026-05-12:19-00/22372.ts", urls[0])

    def test_accepts_colon_seconds_input_timestamp(self):
        urls = build_timeshift_candidate_urls(
            self.creds, "22372", "2026-06-23:04:00:00", 40
        )
        self.assertTrue(self._is_path_form(urls[0]))
        self.assertIn("/40/2026-06-23:04-00/22372.ts", urls[0])
        self.assertIn("/40/2026-06-23:04:00:00/22372.ts", urls[2])

    def test_accepts_underscore_input_timestamp(self):
        # Client may send the underscore shape; PATH form still leads.
        urls = build_timeshift_candidate_urls(self.creds, "22372", "2026-05-12_19-00", 40)
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

    def test_utc_to_brussels_from_unix_epoch(self):
        epoch = str(int(datetime(2026, 6, 8, 17, 0, 0, tzinfo=timezone.utc).timestamp()))
        self.assertEqual(
            convert_timestamp_to_provider_tz(epoch, "Europe/Brussels"),
            "2026-06-08:19-00",
        )

    def test_garbage_timestamp_passthrough(self):
        self.assertEqual(
            convert_timestamp_to_provider_tz("garbage", "Europe/Brussels"),
            "garbage",
        )


class GetProgrammeDurationTests(TestCase):
    """Duration window resolution: programme length + buffer, capped, with a
    safe default whenever the EPG lookup cannot resolve."""

    def _channel_with_programme(self, minutes):
        from datetime import datetime, timedelta, timezone as dt_timezone
        from unittest.mock import MagicMock

        start = datetime(2026, 6, 8, 17, 0, tzinfo=dt_timezone.utc)
        programme = MagicMock(
            start_time=start, end_time=start + timedelta(minutes=minutes)
        )
        channel = MagicMock()
        channel.epg_data.programs.filter.return_value.first.return_value = programme
        return channel

    def test_duration_is_programme_length_plus_buffer(self):
        from apps.timeshift.helpers import get_programme_duration
        # 40-minute programme + 5-minute buffer.
        self.assertEqual(
            get_programme_duration(self._channel_with_programme(40), "2026-06-08:17-00"),
            45,
        )

    def test_duration_capped_at_max(self):
        from apps.timeshift.helpers import get_programme_duration
        self.assertEqual(
            get_programme_duration(self._channel_with_programme(1000), "2026-06-08:17-00"),
            480,
        )

    def test_no_epg_data_falls_back_to_default(self):
        from unittest.mock import MagicMock
        from apps.timeshift.helpers import get_programme_duration
        channel = MagicMock(epg_data=None)
        self.assertEqual(get_programme_duration(channel, "2026-06-08:17-00"), 120)

    def test_no_matching_programme_falls_back_to_default(self):
        from unittest.mock import MagicMock
        from apps.timeshift.helpers import get_programme_duration
        channel = MagicMock()
        channel.epg_data.programs.filter.return_value.first.return_value = None
        self.assertEqual(get_programme_duration(channel, "2026-06-08:17-00"), 120)

    def test_garbage_timestamp_falls_back_to_default(self):
        from unittest.mock import MagicMock
        from apps.timeshift.helpers import get_programme_duration
        self.assertEqual(get_programme_duration(MagicMock(), "garbage"), 120)


class ClientDurationTests(TestCase):
    """Client-supplied programme length: sanitised, buffered for provider lag,
    capped, and preferred over EPG when usable."""

    def test_valid_hint_gets_buffer(self):
        from apps.timeshift.helpers import client_duration_to_window
        self.assertEqual(client_duration_to_window(30), 35)
        self.assertEqual(client_duration_to_window("30"), 35)

    def test_hint_capped_at_max(self):
        from apps.timeshift.helpers import client_duration_to_window
        self.assertEqual(client_duration_to_window(1000), 480)

    def test_unusable_hint_returns_none(self):
        from apps.timeshift.helpers import client_duration_to_window
        for bad in (None, "", "abc", "0", "-5", 0, -10):
            self.assertIsNone(client_duration_to_window(bad))

    def test_resolve_prefers_client_hint(self):
        from unittest.mock import MagicMock
        from apps.timeshift.helpers import resolve_catchup_duration
        # EPG would say 120 (no programme), but a valid hint wins.
        channel = MagicMock(epg_data=None)
        self.assertEqual(
            resolve_catchup_duration(channel, "2026-06-08:17-00", client_hint="30"),
            35,
        )

    def test_resolve_falls_back_to_epg_when_hint_missing(self):
        from unittest.mock import MagicMock
        from apps.timeshift.helpers import resolve_catchup_duration
        channel = MagicMock(epg_data=None)
        self.assertEqual(
            resolve_catchup_duration(channel, "2026-06-08:17-00", client_hint=None),
            120,
        )


class ProgrammeAgeAndStreamOrderTests(TestCase):
    """Archive-age helpers used to prefer deep catch-up providers first."""

    def test_programme_age_days_ceil(self):
        now = datetime(2026, 7, 16, 12, 0, 0)
        self.assertEqual(
            programme_age_days("2026-07-12:12-00", now=now),
            4,
        )
        self.assertEqual(
            programme_age_days("2026-07-15:12-00", now=now),
            1,
        )
        self.assertEqual(
            programme_age_days("2026-07-16:12-00", now=now),
            0,
        )

    def test_programme_age_days_unparseable(self):
        self.assertIsNone(programme_age_days("garbage"))

    def test_order_prefers_covering_streams_then_fallback(self):
        from types import SimpleNamespace

        now = datetime(2026, 7, 16, 12, 0, 0)
        streams = [
            SimpleNamespace(catchup_days=2, name="p1"),
            SimpleNamespace(catchup_days=1, name="p2"),
            SimpleNamespace(catchup_days=5, name="p3"),
        ]
        ordered = order_catchup_streams_for_timestamp(
            streams, "2026-07-12:12-00", now=now
        )
        self.assertEqual([s.name for s in ordered], ["p3", "p1", "p2"])

    def test_order_keeps_channel_order_within_groups(self):
        from types import SimpleNamespace

        now = datetime(2026, 7, 16, 12, 0, 0)
        streams = [
            SimpleNamespace(catchup_days=7, name="a"),
            SimpleNamespace(catchup_days=2, name="b"),
            SimpleNamespace(catchup_days=14, name="c"),
            SimpleNamespace(catchup_days=1, name="d"),
        ]
        ordered = order_catchup_streams_for_timestamp(
            streams, "2026-07-12:12-00", now=now
        )
        self.assertEqual([s.name for s in ordered], ["a", "c", "b", "d"])

    def test_unknown_catchup_days_stay_preferred(self):
        from types import SimpleNamespace

        now = datetime(2026, 7, 16, 12, 0, 0)
        streams = [
            SimpleNamespace(catchup_days=2, name="short"),
            SimpleNamespace(catchup_days=0, name="unknown"),
            SimpleNamespace(catchup_days=5, name="deep"),
        ]
        ordered = order_catchup_streams_for_timestamp(
            streams, "2026-07-12:12-00", now=now
        )
        self.assertEqual([s.name for s in ordered], ["unknown", "deep", "short"])

    def test_unparseable_timestamp_preserves_order(self):
        from types import SimpleNamespace

        streams = [
            SimpleNamespace(catchup_days=2, name="a"),
            SimpleNamespace(catchup_days=5, name="b"),
        ]
        ordered = order_catchup_streams_for_timestamp(streams, "garbage")
        self.assertEqual([s.name for s in ordered], ["a", "b"])
