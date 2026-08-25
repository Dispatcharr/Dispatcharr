from xml.etree.ElementTree import fromstring

from django.test import SimpleTestCase

from apps.epg.tasks import extract_custom_properties
from apps.epg.utils import fill_original_air_date_if_missing


def _programme(*children_xml):
    children = '\n'.join(children_xml)
    return fromstring(
        f'<programme start="20260728183000 +0000" stop="20260728190000 +0000" '
        f'channel="test.channel">'
        f'<title>Test Show</title>'
        f'{children}'
        f'</programme>'
    )


class ExtractCustomPropertiesEpisodeNumTests(SimpleTestCase):
    def test_bare_episode_num_defaults_to_onscreen(self):
        props = extract_custom_properties(_programme('<episode-num>E119</episode-num>'))
        self.assertEqual(props.get('onscreen_episode'), 'E119')

    def test_empty_system_defaults_to_onscreen(self):
        props = extract_custom_properties(
            _programme('<episode-num system="">E119</episode-num>')
        )
        self.assertEqual(props.get('onscreen_episode'), 'E119')

    def test_explicit_onscreen_preserved(self):
        props = extract_custom_properties(
            _programme('<episode-num system="onscreen">S01E05</episode-num>')
        )
        self.assertEqual(props.get('onscreen_episode'), 'S01E05')
        self.assertEqual(props.get('season'), 1)
        self.assertEqual(props.get('episode'), 5)

    def test_explicit_xmltv_ns_still_parsed(self):
        props = extract_custom_properties(
            _programme('<episode-num system="xmltv_ns">0.118.</episode-num>')
        )
        self.assertNotIn('onscreen_episode', props)
        self.assertEqual(props.get('season'), 1)
        self.assertEqual(props.get('episode'), 119)


class OriginalAirDateIngestTests(SimpleTestCase):
    def test_previously_shown_start_is_preferred(self):
        props = extract_custom_properties(_programme(
            '<date>2020</date>',
            '<episode-num system="original-air-date">2026-06-24 00:00:00</episode-num>',
            '<previously-shown start="20260624000000" />',
        ))
        self.assertEqual(
            props['previously_shown_details']['start'],
            '20260624000000',
        )
        self.assertEqual(props['date'], '2020')

    def test_original_air_date_episode_num_fills_missing_start(self):
        props = extract_custom_properties(_programme(
            '<date>2020</date>',
            '<episode-num system="original-air-date">2026-06-24 00:00:00</episode-num>',
            '<previously-shown />',
        ))
        self.assertTrue(props.get('previously_shown'))
        self.assertEqual(
            props['previously_shown_details']['start'],
            '2026-06-24 00:00:00',
        )
        self.assertEqual(props['date'], '2020')

    def test_original_air_date_episode_num_works_without_previously_shown(self):
        props = extract_custom_properties(_programme(
            '<episode-num system="original-air-date">2026-06-24 00:00:00</episode-num>',
        ))
        self.assertNotIn('previously_shown', props)
        self.assertEqual(
            props['previously_shown_details']['start'],
            '2026-06-24 00:00:00',
        )

    def test_date_is_not_used_as_original_air_fallback(self):
        props = extract_custom_properties(_programme(
            '<date>20260624</date>',
            '<previously-shown />',
        ))
        self.assertEqual(props['date'], '20260624')
        self.assertNotIn('previously_shown_details', props)

    def test_preserves_channel_when_filling_start_from_episode_num(self):
        props = extract_custom_properties(_programme(
            '<episode-num system="original-air-date">2026-06-24 00:00:00</episode-num>',
            '<previously-shown channel="channel-one.tv" />',
        ))
        self.assertEqual(
            props['previously_shown_details'],
            {
                'channel': 'channel-one.tv',
                'start': '2026-06-24 00:00:00',
            },
        )


class FillOriginalAirDateIfMissingTests(SimpleTestCase):
    def test_sets_start_when_absent(self):
        props = {}
        fill_original_air_date_if_missing(props, '2016-12-15')
        self.assertEqual(props['previously_shown_details']['start'], '2016-12-15')

    def test_does_not_overwrite_existing_start(self):
        props = {'previously_shown_details': {'start': '2007-07-01'}}
        fill_original_air_date_if_missing(props, '2016-12-15')
        self.assertEqual(props['previously_shown_details']['start'], '2007-07-01')

    def test_ignores_blank_candidate(self):
        props = {}
        fill_original_air_date_if_missing(props, '  ')
        self.assertNotIn('previously_shown_details', props)

    def test_sd_style_mapping_keeps_date_and_sets_start(self):
        """Mirrors Schedules Direct ingest: date stays, canonical start is filled."""
        props = {'previously_shown': True}
        original_air_date = '2016-12-15'
        props['date'] = original_air_date
        fill_original_air_date_if_missing(props, original_air_date)
        self.assertEqual(props['date'], '2016-12-15')
        self.assertEqual(props['previously_shown_details']['start'], '2016-12-15')
