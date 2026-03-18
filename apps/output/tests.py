from django.test import TestCase, Client
from django.urls import reverse
from apps.channels.models import Channel, ChannelGroup
from apps.epg.models import EPGData, EPGSource
import xml.etree.ElementTree as ET

class OutputM3UTest(TestCase):
    def setUp(self):
        self.client = Client()
    
    def test_generate_m3u_response(self):
        """
        Test that the M3U endpoint returns a valid M3U file.
        """
        url = reverse('output:generate_m3u')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("#EXTM3U", content)

    def test_generate_m3u_response_post_empty_body(self):
        """
        Test that a POST request with an empty body returns 200 OK.
        """
        url = reverse('output:generate_m3u')

        response = self.client.post(url, data=None, content_type='application/x-www-form-urlencoded')
        content = response.content.decode()

        self.assertEqual(response.status_code, 200, "POST with empty body should return 200 OK")
        self.assertIn("#EXTM3U", content)

    def test_generate_m3u_response_post_with_body(self):
        """
        Test that a POST request with a non-empty body returns 403 Forbidden.
        """
        url = reverse('output:generate_m3u')

        response = self.client.post(url, data={'evilstring': 'muhahaha'})

        self.assertEqual(response.status_code, 403, "POST with body should return 403 Forbidden")
        self.assertIn("POST requests with body are not allowed, body is:", response.content.decode())


class OutputEPGXMLEscapingTest(TestCase):
    """Test XML escaping of channel_id attributes in EPG generation"""

    def setUp(self):
        self.client = Client()
        self.group = ChannelGroup.objects.create(name="Test Group")

    def test_channel_id_with_ampersand(self):
        """Test channel ID with ampersand is properly escaped"""
        channel = Channel.objects.create(
            channel_number=1.0,
            name="Test Channel",
            tvg_id="News & Sports",
            channel_group=self.group
        )

        url = reverse('output:generate_epg') + '?tvg_id_source=tvg_id'
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

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
        channel = Channel.objects.create(
            channel_number=2.0,
            name="HD Channel",
            tvg_id="Channel <HD>",
            channel_group=self.group
        )

        url = reverse('output:generate_epg') + '?tvg_id_source=tvg_id'
        response = self.client.get(url)

        content = response.content.decode()
        self.assertIn('id="Channel &lt;HD&gt;"', content)

        try:
            ET.fromstring(content)
        except ET.ParseError as e:
            self.fail(f"Generated EPG with < > is not valid XML: {e}")

    def test_channel_id_with_all_special_chars(self):
        """Test channel ID with all XML special characters"""
        channel = Channel.objects.create(
            channel_number=3.0,
            name="Complex Channel",
            tvg_id='Test & "Special" <Chars>',
            channel_group=self.group
        )

        url = reverse('output:generate_epg') + '?tvg_id_source=tvg_id'
        response = self.client.get(url)

        content = response.content.decode()
        self.assertIn('id="Test &amp; &quot;Special&quot; &lt;Chars&gt;"', content)

        try:
            tree = ET.fromstring(content)
            # Verify we can find the channel with correct ID in parsed tree
            channel_elem = tree.find('.//channel[@id="Test & \\"Special\\" <Chars>"]')
            self.assertIsNotNone(channel_elem)
        except ET.ParseError as e:
            self.fail(f"Generated EPG with all special chars is not valid XML: {e}")

    def test_program_channel_attribute_escaping(self):
        """Test that programme elements also have escaped channel attributes"""
        epg_source = EPGSource.objects.create(name="Test EPG", source_type="dummy")
        epg_data = EPGData.objects.create(name="Test EPG Data", epg_source=epg_source)
        channel = Channel.objects.create(
            channel_number=4.0,
            name="Program Test",
            tvg_id="News & Sports",
            epg_data=epg_data,
            channel_group=self.group
        )

        url = reverse('output:generate_epg') + '?tvg_id_source=tvg_id'
        response = self.client.get(url)

        content = response.content.decode()

        # Check programme elements have escaped channel attributes
        self.assertIn('channel="News &amp; Sports"', content)

        try:
            tree = ET.fromstring(content)
            programmes = tree.findall('.//programme[@channel="News & Sports"]')
            self.assertGreater(len(programmes), 0)
        except ET.ParseError as e:
            self.fail(f"Generated EPG with programme elements is not valid XML: {e}")
