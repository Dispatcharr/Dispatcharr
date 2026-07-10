from django.test import TestCase, Client, SimpleTestCase, RequestFactory
from django.urls import reverse
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.channels.models import Channel, ChannelGroup, ChannelProfile, ChannelProfileMembership
from apps.epg.models import EPGData, EPGSource
from apps.accounts.models import User
from apps.m3u.models import M3UAccount
from apps.output.views import xc_get_live_streams, xc_get_series, xc_get_vod_streams
from apps.vod.models import (
    M3UMovieRelation,
    M3USeriesRelation,
    Movie,
    Series,
    VODCategory,
    VODLogo,
)
import xml.etree.ElementTree as ET
from datetime import timedelta


def _response_text(response):
    """Read body from HttpResponse or StreamingHttpResponse."""
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content).decode()
    return response.content.decode()


def _epg_response_without_redis(cache_key, source, **kwargs):
    """Test helper: stream EPG directly without Redis chunk caching."""
    from django.http import StreamingHttpResponse

    response = StreamingHttpResponse(source(), content_type="application/xml")
    response["Content-Disposition"] = 'attachment; filename="Dispatcharr.xml"'
    response["Cache-Control"] = "no-cache"
    return response


class OutputEndpointTestMixin:
    """Isolate HTTP endpoint tests from network ACL, logging, DB teardown, and Redis."""

    def setUp(self):
        super().setUp()
        self._network_patch = patch(
            "apps.output.views.network_access_allowed",
            return_value=True,
        )
        self._epg_teardown_patch = patch("apps.output.epg._epg_export_teardown")
        self._log_event_patch = patch("apps.output.views.log_system_event")
        self._epg_log_event_patch = patch("apps.output.epg.log_system_event")
        self._close_db_patch = patch("django.db.close_old_connections")
        self._epg_cache_patch = patch(
            "apps.output.epg.stream_cached_response",
            side_effect=_epg_response_without_redis,
        )
        self._network_patch.start()
        self._epg_teardown_patch.start()
        self._log_event_patch.start()
        self._epg_log_event_patch.start()
        self._close_db_patch.start()
        self._epg_cache_patch.start()

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()
        self._epg_cache_patch.stop()
        self._close_db_patch.stop()
        self._epg_log_event_patch.stop()
        self._log_event_patch.stop()
        self._epg_teardown_patch.stop()
        self._network_patch.stop()
        super().tearDown()

    def _create_isolated_profile(self, prefix):
        """New profiles auto-include every channel via signal; clear that for tests."""
        profile = ChannelProfile.objects.create(name=f"{prefix}-{uuid4().hex[:8]}")
        ChannelProfileMembership.objects.filter(channel_profile=profile).delete()
        return profile

    def _add_channel_to_profile(self, profile, group, **kwargs):
        channel = Channel.objects.create(channel_group=group, **kwargs)
        ChannelProfileMembership.objects.create(
            channel_profile=profile,
            channel=channel,
            enabled=True,
        )
        return channel


class OutputM3UTest(OutputEndpointTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.group = ChannelGroup.objects.create(name=f"M3U Group {uuid4().hex[:8]}")
        self.profile = self._create_isolated_profile("m3u")
        self._add_channel_to_profile(
            self.profile,
            self.group,
            channel_number=1.0,
            name="Test M3U Channel",
        )

    def _m3u_url(self):
        return reverse("output:m3u_endpoint", kwargs={"profile_name": self.profile.name})

    def test_generate_m3u_response(self):
        """
        Test that the M3U endpoint returns a valid M3U file.
        """
        response = self.client.get(self._m3u_url())
        self.assertEqual(response.status_code, 200)
        content = _response_text(response)
        self.assertIn("#EXTM3U", content)

    def test_generate_m3u_response_post_empty_body(self):
        """
        Test that a POST request with an empty body returns 200 OK.
        """
        response = self.client.post(
            self._m3u_url(),
            data=None,
            content_type="application/x-www-form-urlencoded",
        )
        content = _response_text(response)

        self.assertEqual(response.status_code, 200, "POST with empty body should return 200 OK")
        self.assertIn("#EXTM3U", content)

    def test_generate_m3u_response_post_with_body(self):
        """
        Test that a POST request with a non-empty body returns 403 Forbidden.
        """
        response = self.client.post(self._m3u_url(), data={"evilstring": "muhahaha"})

        self.assertEqual(response.status_code, 403, "POST with body should return 403 Forbidden")
        self.assertIn("POST requests with body are not allowed", _response_text(response))


class OutputEPGXMLEscapingTest(OutputEndpointTestMixin, TestCase):
    """Test XML escaping of channel_id attributes in EPG generation"""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.group = ChannelGroup.objects.create(name=f"Test Group {uuid4().hex[:8]}")
        self.profile = self._create_isolated_profile("epg-xml")

    def _add_channel(self, **kwargs):
        return self._add_channel_to_profile(self.profile, self.group, **kwargs)

    def _epg_url(self, query="tvg_id_source=tvg_id&days=0&prev_days=0"):
        base = reverse("output:epg_endpoint", kwargs={"profile_name": self.profile.name})
        return f"{base}?{query}"

    def test_channel_id_with_ampersand(self):
        """Test channel ID with ampersand is properly escaped"""
        self._add_channel(
            channel_number=1.0,
            name="Test Channel",
            tvg_id="News & Sports",
        )

        response = self.client.get(self._epg_url())

        self.assertEqual(response.status_code, 200)
        content = _response_text(response)

        # Should contain escaped ampersand
        self.assertIn('id="News &amp; Sports"', content)
        self.assertNotIn('id="News & Sports"', content)

        # Verify XML is parseable
        try:
            ET.fromstring(content)
        except ET.ParseError as e:
            self.fail(f"Generated EPG is not valid XML: {e}")

    def test_channel_id_with_angle_brackets(self):
        """Test channel ID with < and > characters"""
        self._add_channel(
            channel_number=2.0,
            name="HD Channel",
            tvg_id="Channel <HD>",
        )

        response = self.client.get(self._epg_url())

        content = _response_text(response)
        self.assertIn('id="Channel &lt;HD&gt;"', content)

        try:
            ET.fromstring(content)
        except ET.ParseError as e:
            self.fail(f"Generated EPG with < > is not valid XML: {e}")

    def test_channel_id_with_all_special_chars(self):
        """Test channel ID with all XML special characters"""
        expected_id = 'Test & "Special" <Chars>'
        self._add_channel(
            channel_number=3.0,
            name="Complex Channel",
            tvg_id=expected_id,
        )

        response = self.client.get(self._epg_url())

        content = _response_text(response)
        self.assertIn('id="Test &amp; &quot;Special&quot; &lt;Chars&gt;"', content)

        try:
            tree = ET.fromstring(content)
            channel_elem = next(
                (
                    elem
                    for elem in tree.findall(".//channel")
                    if elem.get("id") == expected_id
                ),
                None,
            )
            self.assertIsNotNone(channel_elem)
        except ET.ParseError as e:
            self.fail(f"Generated EPG with all special chars is not valid XML: {e}")

    def test_program_channel_attribute_escaping(self):
        """Test that programme elements also have escaped channel attributes"""
        epg_source = EPGSource.objects.create(name="Test EPG", source_type="dummy")
        epg_data = EPGData.objects.create(name="Test EPG Data", epg_source=epg_source)
        self._add_channel(
            channel_number=4.0,
            name="Program Test",
            tvg_id="News & Sports",
            epg_data=epg_data,
        )

        response = self.client.get(self._epg_url())

        content = _response_text(response)

        # Check programme elements have escaped channel attributes
        self.assertIn('channel="News &amp; Sports"', content)

        try:
            tree = ET.fromstring(content)
            programmes = [
                programme
                for programme in tree.findall(".//programme")
                if programme.get("channel") == "News & Sports"
            ]
            self.assertGreater(len(programmes), 0)
        except ET.ParseError as e:
            self.fail(f"Generated EPG with programme elements is not valid XML: {e}")

    def test_programmes_emitted_in_start_time_order(self):
        """Programmes for a channel are emitted in start_time order, not insert order."""
        from django.utils import timezone
        from apps.epg.models import ProgramData

        epg_source = EPGSource.objects.create(name="Real EPG", source_type="xmltv")
        epg_data = EPGData.objects.create(name="Station", epg_source=epg_source, tvg_id="station1")
        self._add_channel(
            channel_number=149.0,
            name="Food Network",
            tvg_id="station1",
            epg_data=epg_data,
        )
        now = timezone.now()
        # Insert out of chronological order so id order != start_time order.
        ProgramData.objects.create(
            epg=epg_data,
            start_time=now + timedelta(days=3),
            end_time=now + timedelta(days=3, hours=1),
            title="Third",
            tvg_id="station1",
        )
        ProgramData.objects.create(
            epg=epg_data,
            start_time=now + timedelta(days=1),
            end_time=now + timedelta(days=1, hours=1),
            title="First",
            tvg_id="station1",
        )
        ProgramData.objects.create(
            epg=epg_data,
            start_time=now + timedelta(days=2),
            end_time=now + timedelta(days=2, hours=1),
            title="Second",
            tvg_id="station1",
        )

        content = _response_text(self.client.get(self._epg_url("tvg_id_source=tvg_id&days=7")))

        self.assertLess(content.find('<title>First</title>'), content.find('<title>Second</title>'))
        self.assertLess(content.find('<title>Second</title>'), content.find('<title>Third</title>'))


class OutputEPGCustomDummyTest(TestCase):
    """Custom dummy EPG must not fall back to default when pattern matched but event is outside window."""

    def setUp(self):
        self.group = ChannelGroup.objects.create(name="Sports Group")

    def test_custom_dummy_outside_window_fills_with_ended_programmes(self):
        from django.utils import timezone
        from apps.output.views import generate_dummy_programs

        epg_source = EPGSource.objects.create(
            name="NHL Dummy",
            source_type="dummy",
            custom_properties={
                "title_pattern": r"(?<league>.*)\s\d+:\s(?<team1>.*?)(?:\s+vs\s+)(?<team2>.*?)\s*@.*",
                "time_pattern": r"(?<hour>\d{1,2}):(?<minute>\d{2})\s*(?<ampm>AM|PM)",
                "date_pattern": r"@ (?<month>[A-Za-z]+)\s+(?<day>\d{1,2})",
                "timezone": "US/Eastern",
                "program_duration": 180,
            },
        )
        channel_name = (
            "NHL 01: Washington Capitals vs Philadelphia Flyers @ April 16 07:30 PM ET"
        )
        now = timezone.now()
        lookback = now - timedelta(days=7)

        programs = generate_dummy_programs(
            channel_id="nhl01",
            channel_name=channel_name,
            num_days=7,
            epg_source=epg_source,
            export_lookback=lookback,
            export_cutoff=now + timedelta(days=7),
        )

        self.assertGreater(len(programs), 0)
        self.assertTrue(
            all(p['end_time'] >= lookback for p in programs),
            "All programmes should fall inside the export window",
        )
        self.assertTrue(
            any('Ended' in p['description'] for p in programs),
            "Past events outside the window should still show ended filler",
        )
        for program in programs:
            start = program['start_time']
            self.assertEqual(start.second, 0)
            self.assertEqual(start.microsecond, 0)
            self.assertIn(
                start.minute, (0, 30),
                "Filler programmes should start on half-hour boundaries",
            )
        self.assertGreaterEqual(programs[0]['start_time'], lookback)

    def test_custom_dummy_future_event_fills_grid_window_with_upcoming(self):
        """Grid-style window: future event should show upcoming filler, not empty."""
        from django.utils import timezone
        from apps.output.epg import _programme_overlaps_export_window, generate_dummy_programs

        epg_source = EPGSource.objects.create(
            name="NHL Dummy Future",
            source_type="dummy",
            custom_properties={
                "title_pattern": r"(?<league>.*)\s\d+:\s(?<team1>.*?)(?:\s+vs\s+)(?<team2>.*?)\s*@.*",
                "time_pattern": r"(?<hour>\d{1,2}):(?<minute>\d{2})\s*(?<ampm>AM|PM)",
                "date_pattern": r"@ (?<month>[A-Za-z]+)\s+(?<day>\d{1,2})",
                "timezone": "US/Eastern",
                "program_duration": 180,
            },
        )
        now = timezone.now()
        grid_start = now - timedelta(hours=1)
        grid_end = now + timedelta(hours=24)
        future = now + timedelta(days=3)
        channel_name = (
            f"NHL 01: Washington Capitals vs Philadelphia Flyers @ "
            f"{future.strftime('%B')} {future.day} 07:30 PM ET"
        )

        programs = generate_dummy_programs(
            channel_id="nhl01",
            channel_name=channel_name,
            num_days=1,
            epg_source=epg_source,
            export_lookback=grid_start,
            export_cutoff=grid_end,
        )

        self.assertGreater(len(programs), 0)
        self.assertTrue(
            all(
                _programme_overlaps_export_window(
                    p["start_time"], p["end_time"], grid_start, grid_end
                )
                for p in programs
            ),
            "All programmes should overlap the grid query window",
        )
        self.assertTrue(
            any("Upcoming" in p.get("description", "") for p in programs),
            "Future events outside the window should show upcoming filler",
        )


class OutputEPGHelperTest(SimpleTestCase):
    def test_ceil_to_half_hour_on_boundary(self):
        from django.utils import timezone
        from apps.output.epg import _ceil_to_half_hour

        dt = timezone.now().replace(minute=30, second=0, microsecond=0)
        self.assertEqual(_ceil_to_half_hour(dt), dt)

    def test_ceil_to_half_hour_rounds_up(self):
        from django.utils import timezone
        from apps.output.epg import _ceil_to_half_hour

        dt = timezone.now().replace(minute=17, second=42, microsecond=123456)
        aligned = _ceil_to_half_hour(dt)
        self.assertEqual(aligned.minute, 30)
        self.assertEqual(aligned.second, 0)
        self.assertGreaterEqual(aligned, dt.replace(microsecond=0))

    def test_ceil_to_half_hour_past_boundary_second(self):
        from django.utils import timezone
        from apps.output.epg import _ceil_to_half_hour

        dt = timezone.now().replace(minute=0, second=52, microsecond=123456)
        aligned = _ceil_to_half_hour(dt)
        self.assertEqual(aligned.minute, 30)
        self.assertEqual(aligned.second, 0)
        self.assertGreaterEqual(aligned, dt.replace(microsecond=0))


class XcVodSeriesDistinctTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-{uuid4().hex[:8]}",
            password="pass",
            custom_properties={"xc_password": "xcpass"},
        )
        self.request = self.factory.get("/player_api.php")

    def _account(self, name, *, priority=0, is_active=True):
        return M3UAccount.objects.create(
            name=name,
            server_url="http://example.com",
            priority=priority,
            is_active=is_active,
        )

    def test_vod_streams_picks_highest_priority_relation(self):
        low = self._account(f"low-{uuid4().hex[:6]}", priority=1)
        high = self._account(f"high-{uuid4().hex[:6]}", priority=10)
        movie = Movie.objects.create(name="Shared Movie", year=2020)
        M3UMovieRelation.objects.create(
            m3u_account=low,
            movie=movie,
            stream_id="low-stream",
            container_extension="mkv",
        )
        M3UMovieRelation.objects.create(
            m3u_account=high,
            movie=movie,
            stream_id="high-stream",
            container_extension="mp4",
        )

        streams = xc_get_vod_streams(self.request, self.user)

        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["name"], "Shared Movie")
        self.assertEqual(streams[0]["container_extension"], "mp4")

    def test_vod_streams_excludes_inactive_accounts(self):
        active = self._account(f"active-{uuid4().hex[:6]}", priority=1)
        inactive = self._account(
            f"inactive-{uuid4().hex[:6]}", priority=99, is_active=False
        )
        active_movie = Movie.objects.create(name="Active Movie")
        inactive_movie = Movie.objects.create(name="Inactive Only Movie")
        M3UMovieRelation.objects.create(
            m3u_account=active,
            movie=active_movie,
            stream_id="active-1",
        )
        M3UMovieRelation.objects.create(
            m3u_account=inactive,
            movie=inactive_movie,
            stream_id="inactive-1",
        )

        streams = xc_get_vod_streams(self.request, self.user)

        names = {s["name"] for s in streams}
        self.assertEqual(names, {"Active Movie"})

    def test_vod_streams_category_filter(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        action = VODCategory.objects.create(name="Action", category_type="movie")
        comedy = VODCategory.objects.create(name="Comedy", category_type="movie")
        action_movie = Movie.objects.create(name="Action Movie")
        comedy_movie = Movie.objects.create(name="Comedy Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=action_movie,
            category=action,
            stream_id="action-1",
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=comedy_movie,
            category=comedy,
            stream_id="comedy-1",
        )

        streams = xc_get_vod_streams(self.request, self.user, category_id=action.id)

        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["name"], "Action Movie")
        self.assertEqual(streams[0]["category_id"], str(action.id))

    def test_vod_streams_sorted_alphabetically_by_name(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        zebra = Movie.objects.create(name="Zebra Film")
        apple = Movie.objects.create(name="Apple Film")
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=zebra, stream_id="z-1"
        )
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=apple, stream_id="a-1"
        )

        streams = xc_get_vod_streams(self.request, self.user)

        self.assertEqual([s["name"] for s in streams], ["Apple Film", "Zebra Film"])

    def test_vod_streams_includes_metadata_fields(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        movie = Movie.objects.create(
            name="Rich Movie",
            description="A plot",
            genre="Drama",
            year=2021,
            rating="8",
            custom_properties={
                "director": "Dir",
                "actors": "Cast",
                "release_date": "2021-01-01",
                "youtube_trailer": "yt123",
            },
        )
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="rich-1",
            container_extension="avi",
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertEqual(stream["plot"], "A plot")
        self.assertEqual(stream["genre"], "Drama")
        self.assertEqual(stream["year"], 2021)
        self.assertEqual(stream["director"], "Dir")
        self.assertEqual(stream["cast"], "Cast")
        self.assertEqual(stream["release_date"], "2021-01-01")
        self.assertEqual(stream["trailer"], "yt123")
        self.assertEqual(stream["container_extension"], "avi")

    def test_vod_streams_stream_icon_uses_logo_id_without_logo_join(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Poster", url="http://example.com/poster.png")
        movie = Movie.objects.create(name="Logo Movie", logo=logo)
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="logo-1",
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIn(f"/{logo.id}/", stream["stream_icon"])

    def test_series_picks_highest_priority_relation(self):
        low = self._account(f"low-{uuid4().hex[:6]}", priority=1)
        high = self._account(f"high-{uuid4().hex[:6]}", priority=10)
        series = Series.objects.create(name="Shared Series", year=2019)
        M3USeriesRelation.objects.create(
            m3u_account=low,
            series=series,
            external_series_id="low-series",
        )
        high_rel = M3USeriesRelation.objects.create(
            m3u_account=high,
            series=series,
            external_series_id="high-series",
        )

        results = xc_get_series(self.request, self.user)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Shared Series")
        self.assertEqual(results[0]["series_id"], high_rel.id)

    def test_series_excludes_inactive_accounts(self):
        active = self._account(f"active-{uuid4().hex[:6]}")
        inactive = self._account(f"inactive-{uuid4().hex[:6]}", is_active=False)
        active_series = Series.objects.create(name="Active Series")
        inactive_series = Series.objects.create(name="Inactive Only Series")
        M3USeriesRelation.objects.create(
            m3u_account=active,
            series=active_series,
            external_series_id="active-s",
        )
        M3USeriesRelation.objects.create(
            m3u_account=inactive,
            series=inactive_series,
            external_series_id="inactive-s",
        )

        results = xc_get_series(self.request, self.user)

        self.assertEqual({r["name"] for r in results}, {"Active Series"})

    def test_series_sorted_alphabetically_by_name(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        z = Series.objects.create(name="Zulu Show")
        a = Series.objects.create(name="Alpha Show")
        M3USeriesRelation.objects.create(
            m3u_account=account, series=z, external_series_id="z"
        )
        M3USeriesRelation.objects.create(
            m3u_account=account, series=a, external_series_id="a"
        )

        results = xc_get_series(self.request, self.user)

        self.assertEqual([r["name"] for r in results], ["Alpha Show", "Zulu Show"])

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL-specific query shape")
    def test_vod_streams_dedupe_query_avoids_movie_join(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        movie = Movie.objects.create(name="Query Shape Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=movie, stream_id="qs-1"
        )

        with CaptureQueriesContext(connection) as ctx:
            xc_get_vod_streams(self.request, self.user)

        distinct_queries = [q for q in ctx.captured_queries if "DISTINCT" in q["sql"]]
        self.assertEqual(len(distinct_queries), 1)
        self.assertNotIn('"vod_movie"', distinct_queries[0]["sql"])
        self.assertNotIn('"vod_vodlogo"', distinct_queries[0]["sql"])

        fetch_queries = [
            q
            for q in ctx.captured_queries
            if '"vod_movie"' in q["sql"] and "DISTINCT" not in q["sql"]
        ]
        self.assertGreaterEqual(len(fetch_queries), 1)
        fetch_sql = fetch_queries[0]["sql"]
        self.assertNotIn('"vod_vodlogo"', fetch_sql)
        self.assertNotIn('"vod_vodcategory"', fetch_sql)

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL-specific query shape")
    def test_series_dedupe_query_avoids_series_join(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        series = Series.objects.create(name="Query Shape Series")
        M3USeriesRelation.objects.create(
            m3u_account=account, series=series, external_series_id="qs-s"
        )

        with CaptureQueriesContext(connection) as ctx:
            xc_get_series(self.request, self.user)

        distinct_queries = [q for q in ctx.captured_queries if "DISTINCT" in q["sql"]]
        self.assertEqual(len(distinct_queries), 1)
        self.assertNotIn('"vod_series"', distinct_queries[0]["sql"])

        fetch_queries = [
            q
            for q in ctx.captured_queries
            if '"vod_series"' in q["sql"] and "DISTINCT" not in q["sql"]
        ]
        self.assertGreaterEqual(len(fetch_queries), 1)
        fetch_sql = fetch_queries[0]["sql"]
        self.assertNotIn('"vod_vodlogo"', fetch_sql)
        self.assertNotIn('"vod_vodcategory"', fetch_sql)


XC_VOD_STREAM_KEYS = frozenset({
    "num", "name", "stream_type", "stream_id", "stream_icon", "rating",
    "rating_5based", "added", "is_adult", "tmdb_id", "imdb_id", "trailer",
    "plot", "genre", "year", "director", "cast", "release_date", "category_id",
    "category_ids", "container_extension", "custom_sid", "direct_source",
})

XC_SERIES_KEYS = frozenset({
    "num", "name", "series_id", "cover", "plot", "cast", "director", "genre",
    "release_date", "releaseDate", "last_modified", "rating", "rating_5based",
    "backdrop_path", "youtube_trailer", "episode_run_time", "category_id",
    "category_ids", "tmdb_id", "imdb_id",
})


class XcVodSeriesRegressionTests(TestCase):
    """Full output-shape and edge-case regressions for XC list endpoints."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-reg-{uuid4().hex[:8]}",
            password="pass",
            custom_properties={"xc_password": "xcpass"},
        )
        self.request = self.factory.get("/player_api.php")

    def _account(self, name, *, priority=0):
        return M3UAccount.objects.create(
            name=name,
            server_url="http://example.com",
            priority=priority,
        )

    def test_vod_streams_empty_library(self):
        self.assertEqual(xc_get_vod_streams(self.request, self.user), [])

    def test_series_empty_library(self):
        self.assertEqual(xc_get_series(self.request, self.user), [])

    def test_vod_streams_response_keys(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        movie = Movie.objects.create(name="Schema Movie", rating="10")
        M3UMovieRelation.objects.create(
            m3u_account=account, movie=movie, stream_id="schema-1"
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertEqual(set(stream.keys()), XC_VOD_STREAM_KEYS)
        self.assertEqual(stream["stream_type"], "movie")
        self.assertEqual(stream["stream_id"], movie.id)
        self.assertEqual(stream["rating_5based"], 5.0)
        self.assertEqual(stream["custom_sid"], None)
        self.assertEqual(stream["direct_source"], "")

    def test_vod_streams_null_optional_fields(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        movie = Movie.objects.create(name="Sparse Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="sparse-1",
            container_extension=None,
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIsNone(stream["stream_icon"])
        self.assertEqual(stream["category_id"], "0")
        self.assertEqual(stream["category_ids"], [])
        self.assertEqual(stream["container_extension"], "mp4")
        self.assertEqual(stream["plot"], "")
        self.assertEqual(stream["trailer"], "")
        self.assertEqual(stream["tmdb_id"], "")
        self.assertEqual(stream["imdb_id"], "")

    def test_vod_streams_category_from_winning_relation(self):
        """Category must come from the highest-priority relation, not any relation."""
        low = self._account(f"low-{uuid4().hex[:6]}", priority=1)
        high = self._account(f"high-{uuid4().hex[:6]}", priority=10)
        action = VODCategory.objects.create(name="Action", category_type="movie")
        comedy = VODCategory.objects.create(name="Comedy", category_type="movie")
        movie = Movie.objects.create(name="Dual Category Movie")
        M3UMovieRelation.objects.create(
            m3u_account=low,
            movie=movie,
            category=action,
            stream_id="low-cat",
        )
        M3UMovieRelation.objects.create(
            m3u_account=high,
            movie=movie,
            category=comedy,
            stream_id="high-cat",
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertEqual(stream["category_id"], str(comedy.id))
        self.assertEqual(stream["category_ids"], [comedy.id])

    def test_series_response_keys_and_metadata(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Cover", url="http://example.com/cover.png")
        category = VODCategory.objects.create(name="Drama", category_type="series")
        series = Series.objects.create(
            name="Schema Series",
            description="Series plot",
            genre="Sci-Fi",
            year=2022,
            rating="8",
            tmdb_id="tm123",
            imdb_id="tt123",
            logo=logo,
            custom_properties={
                "cast": "Actor A",
                "director": "Director B",
                "release_date": "2022-06-01",
                "backdrop_path": ["/img1.jpg"],
                "youtube_trailer": "yt-series",
                "episode_run_time": "45",
            },
        )
        relation = M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            category=category,
            external_series_id="schema-s",
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertEqual(set(row.keys()), XC_SERIES_KEYS)
        self.assertEqual(row["series_id"], relation.id)
        self.assertIn(f"/{logo.id}/", row["cover"])
        self.assertEqual(row["plot"], "Series plot")
        self.assertEqual(row["cast"], "Actor A")
        self.assertEqual(row["director"], "Director B")
        self.assertEqual(row["genre"], "Sci-Fi")
        self.assertEqual(row["release_date"], "2022-06-01")
        self.assertEqual(row["releaseDate"], "2022-06-01")
        self.assertEqual(row["backdrop_path"], ["/img1.jpg"])
        self.assertEqual(row["youtube_trailer"], "yt-series")
        self.assertEqual(row["episode_run_time"], "45")
        self.assertEqual(row["tmdb_id"], "tm123")
        self.assertEqual(row["imdb_id"], "tt123")
        self.assertEqual(row["category_id"], str(category.id))
        self.assertEqual(row["category_ids"], [category.id])
        self.assertEqual(row["last_modified"], str(int(relation.updated_at.timestamp())))

    def test_series_null_optional_fields(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        series = Series.objects.create(name="Sparse Series")
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="sparse-s",
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertIsNone(row["cover"])
        self.assertEqual(row["category_id"], "0")
        self.assertEqual(row["category_ids"], [])
        self.assertEqual(row["release_date"], "")
        self.assertEqual(row["releaseDate"], "")
        self.assertEqual(row["backdrop_path"], [])
        self.assertEqual(row["youtube_trailer"], "")
        self.assertEqual(row["episode_run_time"], "")

    def test_series_release_date_falls_back_to_year(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        series = Series.objects.create(name="Year Only", year=2018)
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="year-s",
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertEqual(row["release_date"], "2018")
        self.assertEqual(row["releaseDate"], "2018")

    def test_priority_tiebreaker_uses_lower_relation_id(self):
        """Same priority: DISTINCT ON tie-breaks on relation id ascending."""
        a1 = self._account(f"a1-{uuid4().hex[:6]}", priority=5)
        a2 = self._account(f"a2-{uuid4().hex[:6]}", priority=5)
        movie = Movie.objects.create(name="Tie Movie")
        first = M3UMovieRelation.objects.create(
            m3u_account=a1,
            movie=movie,
            stream_id="first",
            container_extension="mkv",
        )
        M3UMovieRelation.objects.create(
            m3u_account=a2,
            movie=movie,
            stream_id="second",
            container_extension="mp4",
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertEqual(stream["container_extension"], first.container_extension)


class XcLiveStreamsNullChannelNumberTests(TestCase):
    """XC live streams must not crash when a visible channel has no channel number."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-live-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.request = self.factory.get("/player_api.php")
        self.group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")

    def test_live_streams_assigns_number_for_null_channel_number(self):
        numbered = Channel.objects.create(
            name="Numbered",
            channel_number=5,
            channel_group=self.group,
            user_level=0,
        )
        unnumbered = Channel.objects.create(
            name="Mapped Ch",
            channel_number=None,
            channel_group=self.group,
            user_level=0,
            hidden_from_output=False,
        )

        streams = xc_get_live_streams(self.request, self.user)

        self.assertEqual(len(streams), 2)
        by_id = {s["stream_id"]: s for s in streams}
        self.assertEqual(by_id[numbered.id]["num"], 5)
        self.assertIn(unnumbered.id, by_id)
        self.assertIsInstance(by_id[unnumbered.id]["num"], int)
        self.assertNotIn(by_id[unnumbered.id]["num"], {5})


class XcXmltvNullChannelNumberTests(OutputEndpointTestMixin, TestCase):
    """XC XMLTV EPG must not crash when a visible channel has no channel number."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.user = User.objects.create_user(
            username=f"xc-epg-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")

    def test_xmltv_epg_assigns_number_for_null_channel_number(self):
        Channel.objects.create(
            name="Numbered",
            channel_number=5,
            channel_group=self.group,
            user_level=0,
        )
        Channel.objects.create(
            name="Unnumbered",
            channel_number=None,
            channel_group=self.group,
            user_level=0,
            hidden_from_output=False,
        )

        response = self.client.get(
            reverse("xc_xmltv"),
            {
                "username": self.user.username,
                "password": "xcpass",
                "tvg_id_source": "channel_number",
            },
        )

        self.assertEqual(response.status_code, 200)
        content = _response_text(response)
        try:
            ET.fromstring(content)
        except ET.ParseError as exc:
            self.fail(f"Generated XMLTV EPG is not valid XML: {exc}")
        self.assertIn("Unnumbered", content)


class GenerateEpgPrevDaysTests(SimpleTestCase):
    """Profile EPG keeps legacy prev_days=0 unless URL or user setting says otherwise."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("apps.output.epg.stream_cached_response")
    @patch("apps.output.epg.Channel.objects")
    def test_non_xc_epg_defaults_prev_days_to_zero(self, _channels, mock_cache):
        from apps.output.epg import generate_epg

        mock_cache.side_effect = lambda cache_key, _source, **_kwargs: cache_key
        request = self.factory.get("/epg/")

        cache_key = generate_epg(request, profile_name="test", user=None)

        self.assertIn(":p=0:", cache_key)
