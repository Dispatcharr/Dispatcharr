from django.test import TestCase, Client, SimpleTestCase, RequestFactory
from django.urls import reverse
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.channels.models import Channel, ChannelGroup, ChannelOverride, ChannelProfile, ChannelProfileMembership
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

    def test_override_epg_change_invalidates_xmltv_chunk_cache(self):
        """
        XC reads live ProgramData; XMLTV is chunk-cached. Changing the
        effective EPG via ChannelOverride must drop that cache so the next
        /output/epg emits the new station's programmes, not the previous ones.
        """
        from django.utils import timezone
        from apps.channels.models import ChannelOverride
        from apps.epg.models import ProgramData
        from django_redis import get_redis_connection

        # This mixin normally bypasses Redis chunk caching; use the real path here.
        self._epg_cache_patch.stop()
        try:
            epg_source = EPGSource.objects.create(name="Cache EPG Src", source_type="xmltv")
            epg_old = EPGData.objects.create(
                name="Old Station",
                epg_source=epg_source,
                tvg_id="old.station",
            )
            epg_new = EPGData.objects.create(
                name="New Station",
                epg_source=epg_source,
                tvg_id="new.station",
            )
            channel = self._add_channel(
                channel_number=149.0,
                name="Cache Channel",
                tvg_id="cache.channel",
                epg_data=epg_old,
            )
            now = timezone.now()
            ProgramData.objects.create(
                epg=epg_old,
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
                title="OLD PROGRAMME",
                tvg_id="old.station",
            )
            ProgramData.objects.create(
                epg=epg_new,
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
                title="NEW PROGRAMME",
                tvg_id="new.station",
            )

            url = self._epg_url("tvg_id_source=channel_number&days=7")
            before = _response_text(self.client.get(url))
            self.assertIn('<title>OLD PROGRAMME</title>', before)
            self.assertNotIn('<title>NEW PROGRAMME</title>', before)

            redis = get_redis_connection("default")
            cached_before = list(redis.scan_iter(match="epg_content:*", count=200))
            self.assertGreater(len(cached_before), 0, "XMLTV chunk cache should be warm")

            ChannelOverride.objects.create(channel=channel, epg_data=epg_new)

            cached_after = list(redis.scan_iter(match="epg_content:*", count=200))
            self.assertEqual(
                len(cached_after),
                0,
                "Override EPG change must invalidate XMLTV chunk cache",
            )

            after = _response_text(self.client.get(url))
            self.assertIn('<title>NEW PROGRAMME</title>', after)
            self.assertNotIn('<title>OLD PROGRAMME</title>', after)
        finally:
            self._epg_cache_patch.start()


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

    def test_vod_streams_stream_icon_falls_back_to_relation_basic_data(self):
        """No synced VODLogo: fall back to the winning relation's own list-sync icon."""
        account = self._account(f"acct-{uuid4().hex[:6]}")
        movie = Movie.objects.create(name="No Logo Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="no-logo-1",
            custom_properties={
                "basic_data": {"stream_icon": "https://cdn.example.com/icon.jpg"},
            },
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIsNotNone(stream["stream_icon"])
        self.assertIn("/image/", stream["stream_icon"])
        self.assertIn("kind=movie_image", stream["stream_icon"])

    def test_vod_streams_stream_icon_prefers_relation_over_synced_logo(self):
        """Winning relation still beats a shared Movie.logo (last-writer-wins)."""
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Synced", url="http://example.com/synced.png")
        movie = Movie.objects.create(name="Logo Movie", logo=logo)
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="logo-1",
            custom_properties={
                "basic_data": {"stream_icon": "https://cdn.example.com/icon.jpg"},
            },
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIn("/image/", stream["stream_icon"])
        self.assertIn("kind=movie_image", stream["stream_icon"])
        self.assertNotIn(f"/{logo.id}/", stream["stream_icon"])

    def test_vod_streams_stream_icon_ignores_blank_relation_image_keys(self):
        """basic_data is stored raw, so a blank key must not shadow a populated one."""
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Synced", url="http://example.com/synced.png")
        movie = Movie.objects.create(name="Blank Key Movie", logo=logo)
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="blank-key-1",
            custom_properties={
                "basic_data": {
                    "movie_image": "",
                    "stream_icon": "https://cdn.example.com/icon.jpg",
                },
            },
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIn("kind=movie_image", stream["stream_icon"])
        self.assertNotIn(f"/{logo.id}/", stream["stream_icon"])

    def test_vod_streams_stream_icon_ignores_whitespace_only_image_keys(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        movie = Movie.objects.create(name="Whitespace Key Movie")
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="ws-key-1",
            custom_properties={
                "basic_data": {
                    "movie_image": "   ",
                    "stream_icon": "https://cdn.example.com/icon.jpg",
                },
            },
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIn("kind=movie_image", stream["stream_icon"])

    def test_series_backdrop_skips_empty_detailed_array(self):
        """Empty detailed_info.backdrop_path must not block basic_data."""
        account = self._account(f"acct-{uuid4().hex[:6]}")
        series = Series.objects.create(name="Empty Bd Series")
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="empty-bd-s",
            custom_properties={
                "detailed_info": {"backdrop_path": []},
                "basic_data": {"backdrop_path": "https://cdn.example.com/bd.jpg"},
            },
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertEqual(len(row["backdrop_path"]), 1)
        self.assertIn("kind=backdrop", row["backdrop_path"][0])

    def test_vod_streams_stream_icon_falls_back_to_logo_without_relation_art(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Synced", url="http://example.com/synced.png")
        movie = Movie.objects.create(name="Logo Only Movie", logo=logo)
        M3UMovieRelation.objects.create(
            m3u_account=account,
            movie=movie,
            stream_id="logo-only-1",
        )

        stream = xc_get_vod_streams(self.request, self.user)[0]

        self.assertIn(f"/{logo.id}/", stream["stream_icon"])

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

    def test_series_cover_falls_back_to_relation_basic_data(self):
        """No synced VODLogo: fall back to the winning relation's own list-sync cover."""
        account = self._account(f"acct-{uuid4().hex[:6]}")
        series = Series.objects.create(name="No Logo Series")
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="no-logo-s",
            custom_properties={
                "basic_data": {"cover": "https://cdn.example.com/cover.jpg"},
            },
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertIsNotNone(row["cover"])
        self.assertIn("/image/", row["cover"])
        self.assertIn("kind=movie_image", row["cover"])

    def test_series_backdrop_prefers_higher_priority_relation_basic_data(self):
        """Shared Series.custom_properties can be stale; the winning relation's
        own list-sync backdrop should be preferred when it has one."""
        low = self._account(f"low-{uuid4().hex[:6]}", priority=1)
        high = self._account(f"high-{uuid4().hex[:6]}", priority=10)
        series = Series.objects.create(
            name="Multi Provider Series",
            custom_properties={"backdrop_path": ["https://cdn.example.com/stale.jpg"]},
        )
        M3USeriesRelation.objects.create(
            m3u_account=low,
            series=series,
            external_series_id="low-s",
        )
        M3USeriesRelation.objects.create(
            m3u_account=high,
            series=series,
            external_series_id="high-s",
            custom_properties={
                "basic_data": {"backdrop_path": "https://cdn.example.com/fresh.jpg"},
            },
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertEqual(len(row["backdrop_path"]), 1)
        self.assertIn("/image/", row["backdrop_path"][0])
        from hashlib import md5
        expected_v = md5(b"https://cdn.example.com/fresh.jpg").hexdigest()[:8]
        self.assertIn(f"v={expected_v}", row["backdrop_path"][0])

    def test_series_cover_falls_back_to_logo_without_relation_art(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Cover", url="http://example.com/cover.png")
        series = Series.objects.create(name="Logo Only Series", logo=logo)
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="logo-only-s",
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertIn(f"/{logo.id}/", row["cover"])

    def test_series_cover_prefers_relation_over_synced_logo(self):
        account = self._account(f"acct-{uuid4().hex[:6]}")
        logo = VODLogo.objects.create(name="Cover", url="http://example.com/cover.png")
        series = Series.objects.create(name="Both Series", logo=logo)
        M3USeriesRelation.objects.create(
            m3u_account=account,
            series=series,
            external_series_id="both-s",
            custom_properties={
                "basic_data": {"cover": "https://cdn.example.com/cover.jpg"},
            },
        )

        row = xc_get_series(self.request, self.user)[0]

        self.assertIn("/image/", row["cover"])
        self.assertNotIn(f"/{logo.id}/", row["cover"])

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


class XcLiveStreamsCatchupAdvertisingTests(TestCase):
    """XC live streams omit tv_archive when catchup is disabled for the user."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-catchup-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.request = self.factory.get("/player_api.php")
        self.group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")
        self.channel = Channel.objects.create(
            name="Catchup Ch",
            channel_number=1,
            channel_group=self.group,
            user_level=0,
            is_catchup=True,
            catchup_days=7,
        )

    def tearDown(self):
        # CoreSettings writes populate Redis; DB rollback does not clear it.
        from django.core.cache import cache

        cache.clear()

    def test_tv_archive_advertised_when_catchup_enabled(self):
        streams = xc_get_live_streams(self.request, self.user)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["tv_archive"], 1)
        self.assertEqual(streams[0]["tv_archive_duration"], 7)

    def test_tv_archive_cleared_when_user_disables_catchup(self):
        self.user.custom_properties = {
            **(self.user.custom_properties or {}),
            "catchup_enabled": False,
        }
        self.user.save(update_fields=["custom_properties"])
        streams = xc_get_live_streams(self.request, self.user)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["tv_archive"], 0)
        self.assertEqual(streams[0]["tv_archive_duration"], 0)

    def test_tv_archive_cleared_when_system_disables_catchup(self):
        from core.models import SYSTEM_SETTINGS_KEY, CoreSettings

        obj, _ = CoreSettings.objects.get_or_create(
            key=SYSTEM_SETTINGS_KEY,
            defaults={"name": "System Settings", "value": {}},
        )
        value = dict(obj.value or {})
        value["catchup_enabled"] = False
        obj.value = value
        obj.save()
        streams = xc_get_live_streams(self.request, self.user)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0]["tv_archive"], 0)
        self.assertEqual(streams[0]["tv_archive_duration"], 0)


class XcGetEpgCatchupGateTests(TestCase):
    """Catch-up disable clears has_archive; lookback follows prev_days only."""

    def setUp(self):
        from django.core.cache import cache
        from django.utils import timezone

        from apps.epg.models import ProgramData

        cache.clear()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-epg-cu-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")
        self.epg = EPGData.objects.create(tvg_id=f"cu-{uuid4().hex[:8]}", name="CU EPG")
        self.channel = Channel.objects.create(
            name="Catchup EPG Ch",
            channel_number=1,
            channel_group=self.group,
            user_level=0,
            is_catchup=True,
            catchup_days=7,
            epg_data=self.epg,
        )
        now = timezone.now()
        ProgramData.objects.create(
            epg=self.epg,
            start_time=now - timedelta(days=3),
            end_time=now - timedelta(days=3) + timedelta(hours=1),
            title="Past Show",
        )
        ProgramData.objects.create(
            epg=self.epg,
            start_time=now - timedelta(minutes=30),
            end_time=now + timedelta(minutes=30),
            title="Now Show",
        )

    def tearDown(self):
        from django.core.cache import cache

        cache.clear()

    def _listings(self, *, extra_query=None):
        import base64

        from apps.output.views import xc_get_epg

        params = {
            "action": "get_simple_data_table",
            "stream_id": str(self.channel.id),
        }
        if extra_query:
            params.update(extra_query)
        request = self.factory.get("/player_api.php", params)
        listings = xc_get_epg(request, self.user)["epg_listings"]
        for item in listings:
            item["_title"] = base64.b64decode(item["title"]).decode()
        return listings

    def test_catchup_enabled_expands_lookback_from_catchup_days(self):
        listings = self._listings()
        titles = [item["_title"] for item in listings]
        self.assertIn("Past Show", titles)
        past = next(item for item in listings if item["_title"] == "Past Show")
        self.assertEqual(past["has_archive"], 1)

    def test_catchup_disabled_does_not_force_catchup_days_lookback(self):
        """With no prev_days set, disable must not inject channel.catchup_days."""
        self.user.custom_properties = {
            **(self.user.custom_properties or {}),
            "catchup_enabled": False,
        }
        self.user.save(update_fields=["custom_properties"])
        listings = self._listings()
        titles = [item["_title"] for item in listings]
        self.assertNotIn("Past Show", titles)
        self.assertIn("Now Show", titles)

    def test_catchup_disabled_honors_explicit_prev_days(self):
        self.user.custom_properties = {
            **(self.user.custom_properties or {}),
            "catchup_enabled": False,
            "epg_prev_days": 7,
        }
        self.user.save(update_fields=["custom_properties"])
        listings = self._listings()
        titles = [item["_title"] for item in listings]
        self.assertIn("Past Show", titles)
        past = next(item for item in listings if item["_title"] == "Past Show")
        self.assertEqual(past["has_archive"], 0)


class XcGetEpgDummyTests(TestCase):
    """XC single-channel EPG uses shared dummy generation (stream parse + export window)."""

    NHL_PROPS = {
        "title_pattern": r"(?<league>.*)\s\d+:\s(?<team1>.*?)(?:\s+vs\s+)(?<team2>.*?)\s*@.*",
        "time_pattern": r"(?<hour>\d{1,2}):(?<minute>\d{2})\s*(?<ampm>AM|PM)",
        "timezone": "UTC",
        "program_duration": 180,
        "name_source": "stream",
        "stream_index": 1,
        "title_template": "{team1} vs {team2}",
    }

    def setUp(self):
        from django.test import RequestFactory

        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username=f"xc-dummy-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        self.group = ChannelGroup.objects.create(name=f"Group {uuid4().hex[:8]}")
        self.account = M3UAccount.objects.create(
            name=f"XC Dummy {uuid4().hex[:8]}",
            server_url="http://example.com",
            priority=1,
        )
        self.dummy_source = EPGSource.objects.create(
            name="XC Dummy Source",
            source_type="dummy",
            custom_properties=self.NHL_PROPS,
        )
        self.epg_data = EPGData.objects.get(epg_source=self.dummy_source)

    def _listings(self, channel):
        import base64

        from apps.output.views import xc_get_epg

        request = self.factory.get(
            "/player_api.php",
            {
                "action": "get_simple_data_table",
                "stream_id": str(channel.id),
                "days": "1",
            },
        )
        listings = xc_get_epg(request, self.user)["epg_listings"]
        for item in listings:
            item["_title"] = base64.b64decode(item["title"]).decode()
        return listings

    def test_uses_stream_title_for_custom_dummy_regex(self):
        from apps.channels.models import ChannelStream, Stream

        channel = Channel.objects.create(
            name="Unparseable channel title",
            channel_number=42.0,
            channel_group=self.group,
            epg_data=self.epg_data,
        )
        stream = Stream.objects.create(
            name="NHL 01: Capitals vs Flyers @ 11:00 PM ET",
            url="http://example.com/1.ts",
            m3u_account=self.account,
        )
        ChannelStream.objects.create(channel=channel, stream=stream, order=0)

        titles = {item["_title"] for item in self._listings(channel)}

        self.assertIn("Capitals vs Flyers", titles)

    def test_respects_days_export_window(self):
        from django.utils import timezone

        channel = Channel.objects.create(
            name="NHL 01: Capitals vs Flyers @ 11:00 PM ET",
            channel_number=43.0,
            channel_group=self.group,
            epg_data=self.epg_data,
        )
        listings = self._listings(channel)
        now = timezone.now()
        for item in listings:
            start = timezone.datetime.fromtimestamp(int(item["start_timestamp"]), tz=now.tzinfo)
            end = timezone.datetime.fromtimestamp(int(item["stop_timestamp"]), tz=now.tzinfo)
            self.assertLess(start, now + timedelta(days=1, hours=1))
            self.assertGreater(end, now - timedelta(days=1))


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

    @patch("apps.output.epg.stream_cached_response")
    @patch("apps.output.epg.Channel.objects")
    def test_epg_cache_key_includes_request_origin(self, _channels, mock_cache):
        from apps.output.epg import generate_epg

        mock_cache.side_effect = lambda cache_key, _source, **_kwargs: cache_key

        lan_key = generate_epg(
            self.factory.get("/epg/", HTTP_HOST="192.168.1.10:9191"),
            profile_name="test",
            user=None,
        )
        public_key = generate_epg(
            self.factory.get("/epg/", HTTP_HOST="tv.example.com"),
            profile_name="test",
            user=None,
        )
        same_lan_key = generate_epg(
            self.factory.get("/epg/", HTTP_HOST="192.168.1.10:9191"),
            profile_name="test",
            user=None,
        )

        self.assertIn("origin=http://192.168.1.10:9191", lan_key)
        self.assertIn("origin=http://tv.example.com", public_key)
        self.assertNotEqual(lan_key, public_key)
        self.assertEqual(lan_key, same_lan_key)


class GenerateM3UCacheKeyTests(SimpleTestCase):
    """M3U shared cache must not reuse absolute URLs built for a different Host."""

    def setUp(self):
        self.factory = RequestFactory()

    @patch("django.core.cache.cache")
    def test_m3u_cache_key_includes_request_origin(self, mock_cache):
        from apps.output.views import generate_m3u

        mock_cache.get.return_value = "#EXTM3U\n"

        generate_m3u(
            self.factory.get("/m3u/", HTTP_HOST="192.168.1.10:9191"),
            profile_name="test",
            user=None,
        )
        lan_key = mock_cache.get.call_args[0][0]

        generate_m3u(
            self.factory.get("/m3u/", HTTP_HOST="tv.example.com"),
            profile_name="test",
            user=None,
        )
        public_key = mock_cache.get.call_args[0][0]

        generate_m3u(
            self.factory.get("/m3u/", HTTP_HOST="192.168.1.10:9191"),
            profile_name="test",
            user=None,
        )
        same_lan_key = mock_cache.get.call_args[0][0]

        self.assertTrue(lan_key.startswith("m3u_content:"))
        self.assertIn("origin=http://192.168.1.10:9191", lan_key)
        self.assertIn("origin=http://tv.example.com", public_key)
        self.assertNotEqual(lan_key, public_key)
        self.assertEqual(lan_key, same_lan_key)


class XcVodStreamsAdultContentTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.account = M3UAccount.objects.create(
            name=f"vod-adult-{uuid4().hex[:6]}",
            server_url="http://example.com",
            priority=1,
            is_active=True,
        )
        self.safe = Movie.objects.create(name="Family Movie", is_adult=False)
        self.adult = Movie.objects.create(name="Mature Movie", is_adult=True)
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.safe,
            stream_id="safe-1",
        )
        M3UMovieRelation.objects.create(
            m3u_account=self.account,
            movie=self.adult,
            stream_id="adult-1",
        )
        self.request = self.factory.get("/player_api.php")

    def test_vod_streams_emits_is_adult_flag(self):
        user = User.objects.create_user(
            username=f"xc-adult-admin-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={"xc_password": "xcpass"},
        )
        streams = {s["name"]: s for s in xc_get_vod_streams(self.request, user)}
        self.assertEqual(streams["Family Movie"]["is_adult"], 0)
        self.assertEqual(streams["Mature Movie"]["is_adult"], 1)

    def test_hide_adult_content_filters_vod_for_non_admin(self):
        user = User.objects.create_user(
            username=f"xc-adult-hide-{uuid4().hex[:8]}",
            password="pass",
            user_level=0,
            custom_properties={
                "xc_password": "xcpass",
                "hide_adult_content": True,
            },
        )
        names = {s["name"] for s in xc_get_vod_streams(self.request, user)}
        self.assertEqual(names, {"Family Movie"})

    def test_admin_still_sees_adult_vod_when_hide_set(self):
        user = User.objects.create_user(
            username=f"xc-adult-admin-hide-{uuid4().hex[:8]}",
            password="pass",
            user_level=10,
            custom_properties={
                "xc_password": "xcpass",
                "hide_adult_content": True,
            },
        )
        names = {s["name"] for s in xc_get_vod_streams(self.request, user)}
        self.assertEqual(names, {"Family Movie", "Mature Movie"})
