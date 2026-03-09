from django.test import SimpleTestCase

from apps.m3u.tasks import parse_extinf_line


class ParseExtinfLineTests(SimpleTestCase):
    def test_preserves_equals_padding_in_tvg_logo(self):
        line = (
            '#EXTINF:-1 tvg-id="cp_891ee08a2cdfde210ec2c9137127103b" '
            'tvg-chno="1001" '
            'tvg-name="UK Sky Sports Premier League" '
            'tvg-logo="https://e3.365dm.com/tvlogos/channels/1303-Logo.png?'
            'U2t5IFNwb3J0cyBQcmVtaWVyIExlYWd1ZQ==" '
            'group-title="Team Games",UK Sky Sports Premier League'
        )

        parsed = parse_extinf_line(line)

        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["attributes"]["tvg-logo"],
            "https://e3.365dm.com/tvlogos/channels/1303-Logo.png?U2t5IFNwb3J0cyBQcmVtaWVyIExlYWd1ZQ==",
        )
        self.assertEqual(parsed["attributes"]["group-title"], "Team Games")
        self.assertEqual(parsed["name"], "UK Sky Sports Premier League")

    def test_supports_single_quoted_attributes(self):
        line = (
            "#EXTINF:-1 tvg-name='Channel One' tvg-logo='https://example.com/logo==.png' "
            "group-title='Sports',Channel One"
        )

        parsed = parse_extinf_line(line)

        self.assertIsNotNone(parsed)
        self.assertEqual(
            parsed["attributes"]["tvg-logo"],
            "https://example.com/logo==.png",
        )
        self.assertEqual(parsed["attributes"]["group-title"], "Sports")
        self.assertEqual(parsed["display_name"], "Channel One")
