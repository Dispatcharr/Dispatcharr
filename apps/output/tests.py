from django.test import TestCase, Client, SimpleTestCase
from django.urls import reverse
from unittest.mock import patch
from uuid import uuid4
from apps.channels.models import Channel, ChannelGroup, ChannelProfile, ChannelProfileMembership
from apps.epg.models import EPGData, EPGSource
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
