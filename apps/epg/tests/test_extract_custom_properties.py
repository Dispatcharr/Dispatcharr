from xml.etree.ElementTree import fromstring

from django.test import SimpleTestCase

from apps.epg.tasks import extract_custom_properties


def _programme(*episode_num_xml):
    children = '\n'.join(episode_num_xml)
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
